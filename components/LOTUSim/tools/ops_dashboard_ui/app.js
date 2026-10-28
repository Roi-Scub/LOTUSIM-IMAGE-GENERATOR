'use strict';

(() => {
  const $ = id => document.getElementById(id);
  const NS = 'http://www.w3.org/2000/svg';
  const routes = {
    overview: ['Vue d’ensemble', 'Moteurs 3D, LOTUSim et chaîne d’images, réunis au même endroit.'],
    agents: ['Agents & chaîne', 'Comprendre qui travaille, sur quelle étape, à partir de quels signaux.'],
    traffic: ['Trafic coopératif', 'Explorer un plan existant et éditer un brouillon hors ligne, sans application au moteur.'],
    journal: ['Journal d’activité', 'Suivre les événements observés, sans les confondre avec un état courant.'],
    reports: ['Campagnes & rapports', 'Retrouver les captures et les résultats déjà produits.'],
    settings: ['Paramétrage', 'Choisir un profil moteur, composer une campagne et préparer ses fichiers locaux.'],
    assets: ['Modèles 3D', 'Explorer les meshes disponibles et ajouter des fichiers à la bibliothèque locale.'],
  };
  const stateNames = {
    running: 'En cours', ready: 'Disponible', idle: 'En veille', paused: 'En pause',
    stale: 'Signal ancien', unknown: 'Non mesuré', stopped: 'Arrêté', error: 'Incident',
    complete: 'Terminé', completed: 'Terminé', failed: 'Échec', cancelled: 'Annulé', configured: 'Configuré',
    historical: 'Historique', detecting: 'Détection', inferencing: 'Analyse en cours',
    classifying: 'Classification', loading_model: 'Chargement du modèle', preparing: 'Préparation',
    staging: 'Préparation', evaluating: 'Évaluation', reporting: 'Rapport en cours',
    transporting: 'Transport RGB', warming_up: 'Préchauffage', capturing: 'Capture en cours',
    starting: 'Démarrage', complete_cleanup_unconfirmed: 'Terminé · arrêt non confirmé',
  };
  const activeStates = new Set(['running', 'detecting', 'inferencing', 'classifying', 'loading_model',
    'preparing', 'staging', 'evaluating', 'reporting', 'transporting', 'warming_up', 'capturing', 'starting']);
  const healthyStates = new Set(['running', 'ready', 'online', 'available']);
  const errorStates = new Set(['error', 'failed', 'offline']);
  const warningStates = new Set(['stale', 'paused', 'warning', 'degraded', 'configured', 'unconfirmed', 'complete_cleanup_unconfirmed']);
  let current = null;
  let lastSuccess = 0;
  let lastEventId = null;
  let fetchPending = false;
  let eventSource = null;
  let eventStreamOpen = false;
  let transportMode = 'waiting';
  let route = 'overview';
  let previewIdentity = '';
  let connectionFailed = false;

  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined && text !== null) result.textContent = String(text);
    if (className) result.className = className;
    return result;
  }
  function icon(name) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'icon');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS(NS, 'use');
    use.setAttribute('href', '#i-' + name);
    svg.append(use);
    return svg;
  }
  function svgNode(tag, attrs = {}) {
    const result = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs)) result.setAttribute(key, String(value));
    return result;
  }
  function finite(value) { return typeof value === 'number' && Number.isFinite(value); }
  function number(value, digits = 0) {
    return finite(value) ? new Intl.NumberFormat('fr-FR', {maximumFractionDigits: digits}).format(value) : '—';
  }
  function list(value) { return Array.isArray(value) ? value : []; }
  function sourceEngine(value) {
    const source=value?.sourceEngine;
    if(source&&typeof source==='object')return typeof source.label==='string'?source.label:typeof source.id==='string'?source.id:null;
    if(typeof value?.engineLabel==='string'&&value.engineLabel)return value.engineLabel;
    if(typeof source==='string'&&source)return source;
    return typeof value?.engineId==='string'&&value.engineId?value.engineId:null;
  }
  function rendererLabel(data) {
    const renderer=data?.renderer;
    if(renderer?.engineId)return typeof renderer.label==='string'?renderer.label:renderer.engineId;
    if(!renderer&&data?.unity)return 'Unity'; // Actual legacy adapter, never the selected project profile.
    return null;
  }
  function renderEngineProfile(data){
    const selected=data?.engineProfile?.selectedEngine||data?.engineProfile;
    const target=$('engineProfileSummary');if(!target)return;
    const label=typeof selected?.label==='string'?selected.label:typeof selected?.id==='string'?selected.id:null;
    target.textContent=label?'Profil du projet : '+label+(selected.mode==='neutral_contract_only'?' · contrat uniquement':''):'Profil du projet non mesuré';
    target.title='Configuration souhaitée, distincte du moteur qui a réellement produit les images ou les signaux.';
  }
  function timestamp(value) {
    const parsed = typeof value === 'number' ? value * (value < 1e11 ? 1000 : 1) : Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  function time(value, withDate = false) {
    const parsed = timestamp(value);
    if (parsed === null) return 'Heure non mesurée';
    const options = {timeZone: 'Europe/Paris', hour: '2-digit', minute: '2-digit', second: '2-digit'};
    if (withDate) { options.day = '2-digit'; options.month = 'short'; }
    return new Intl.DateTimeFormat('fr-FR', options).format(parsed);
  }
  function ageSeconds(value, fallback = null) {
    const parsed = timestamp(value);
    return parsed === null ? fallback : Math.max(0, (Date.now() - parsed) / 1000);
  }
  function age(value, fallback = null) {
    const seconds = ageSeconds(value, fallback);
    if (!finite(seconds)) return 'Âge non mesuré';
    if (seconds < 5) return 'À l’instant';
    if (seconds < 60) return 'Il y a ' + Math.floor(seconds) + ' s';
    if (seconds < 3600) return 'Il y a ' + Math.floor(seconds / 60) + ' min';
    if (seconds < 86400) return 'Il y a ' + Math.floor(seconds / 3600) + ' h';
    return 'Il y a ' + Math.floor(seconds / 86400) + ' j';
  }
  function stateOf(value) { return String(value?.state || value?.status || 'unknown').toLowerCase(); }
  function activityState(value) {
    const status = String(value?.status || '').toLowerCase();
    if (['complete', 'completed', 'failed', 'cancelled', 'complete_cleanup_unconfirmed'].includes(status)) return status;
    const state = stateOf(value);
    if (errorStates.has(state)) return state;
    if (value?.id === 'scene_preparation' && ['complete', 'completed', 'stale'].includes(state)) return state;
    if (value?.historical === true || value?.kind === 'historical' || value?.archived === true
      || (state === 'ready' && /\barchiv[ée]/i.test(value?.detail || ''))) return 'historical';
    return state;
  }
  function activityLabel(value) {
    const state = activityState(value);
    const historical = value?.historical === true || value?.kind === 'historical';
    return stateLabel(state) + (historical && state !== 'historical' ? ' · historique' : '');
  }
  function hasSceneSnapshot(scene) {
    return !!scene && scene.available !== false && Array.isArray(scene.objects)
      && (scene.available === true || finite(scene.frame) || scene.objects.length > 0);
  }
  function stateLabel(value) { return stateNames[String(value || 'unknown').toLowerCase()] || 'État non confirmé'; }
  function tone(value) {
    value = String(value || 'unknown').toLowerCase();
    if (healthyStates.has(value) || activeStates.has(value)) return 'live';
    if (errorStates.has(value)) return 'error';
    if (warningStates.has(value)) return 'warning';
    if (['complete', 'completed', 'historical'].includes(value)) return 'complete';
    return 'neutral';
  }
  function dot(value) { return node('span', null, 'status-dot ' + tone(value)); }
  function setDot(target, value) { $(target).className = 'status-dot ' + tone(value); }
  function setBadge(target, value, label = null) {
    $(target).className = 'badge ' + tone(value);
    $(target).textContent = label || stateLabel(value);
  }
  function safeURL(value) {
    if (typeof value !== 'string' || !value.trim() || value.includes('\\')) return null;
    try {
      const result = new URL(value, window.location.origin);
      if (result.origin !== window.location.origin || !['http:', 'https:'].includes(result.protocol)) return null;
      return result.pathname + result.search + result.hash;
    } catch (_) { return null; }
  }
  function attachLink(element, value) {
    const url = safeURL(value);
    if (!url) return false;
    element.href = url;
    element.target = '_blank';
    element.rel = 'noopener noreferrer';
    return true;
  }
  function baseName(value) {
    return typeof value === 'string' ? value.replaceAll('\\', '/').split('/').filter(Boolean).pop() || value : '';
  }
  function ratio(done, total) {
    return finite(done) && finite(total) && total > 0 ? Math.max(0, Math.min(1, done / total)) : null;
  }
  function progress(value) {
    if (finite(value?.progress)) {
      return Math.max(0, Math.min(1, value.progress > 1 ? value.progress / 100 : value.progress));
    }
    if (finite(value?.completed) && finite(value?.expected) && value.expected > 0) {
      const regionFraction = finite(value.region) && finite(value.regions) && value.regions > 0
        && value.completed < value.expected ? Math.min(1, value.region / value.regions) : 0;
      return Math.max(0, Math.min(1, (value.completed + regionFraction) / value.expected));
    }
    return null;
  }
  function setWidth(id, value) { $(id).style.width = finite(value) ? Math.max(0, Math.min(100, value * 100)) + '%' : '0%'; }

  function navigate() {
    const requested = location.hash.slice(1);
    route = Object.hasOwn(routes, requested) ? requested : 'overview';
    for (const key of Object.keys(routes)) $('page-' + key).hidden = key !== route;
    document.querySelectorAll('[data-route]').forEach(link => {
      const selected = link.dataset.route === route;
      link.classList.toggle('active', selected);
      if (selected) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    $('breadcrumb').textContent = routes[route][0];
    $('pageTitle').textContent = routes[route][0];
    $('pageSubtitle').textContent = routes[route][1];
    $('modeTag').textContent = route === 'settings' ? 'CONFIGURATION LOCALE' : route === 'assets' ? 'BIBLIOTHÈQUE LOCALE' : route === 'traffic' ? 'BROUILLON HORS LIGNE' : 'LECTURE SEULE';
    if (current && route === 'journal') renderJournal(current);
  }
  function updateConnection() {
    const disconnected = (connectionFailed && !lastSuccess) || (lastSuccess && Date.now() - lastSuccess > 8000);
    const generatedAge = current ? ageSeconds(current.generatedAt) : null;
    const delayed = finite(generatedAge) && generatedAge > 15;
    const mode = disconnected ? 'error' : delayed ? 'warning' : lastSuccess ? 'ready' : 'unknown';
    $('connection').querySelector('.status-dot').className = 'status-dot ' + tone(mode);
    $('connectionText').textContent = disconnected ? lastSuccess ? 'Liaison interrompue' : 'Collecteur inaccessible' : delayed ? 'Collecteur en retard' :
      lastSuccess ? eventStreamOpen ? 'Flux local connecté' : 'Actualisation locale' : 'Connexion…';
    $('sideStatus').textContent = disconnected ? 'Données non actualisées' : delayed ? 'Dernier état conservé' :
      lastSuccess ? 'Connecté à ce Mac' : 'Connexion en attente';
    setDot('sideDot', mode);
    $('offlineNotice').hidden = !disconnected;
    window.LotusimAlerts?.setTransport(disconnected ? {level: 'error', message: 'Liaison avec le collecteur interrompue. Les dernières données restent visibles, mais ne sont plus actualisées.'} :
      delayed ? {level: 'warning', message: 'Le collecteur répond avec un état ancien. Les positions et indicateurs ne prouvent pas une exécution actuelle.'} : null);
    if (current) $('lastSync').textContent = 'Synchronisé à ' + time(current.generatedAt);
  }

  function renderKpis(data) {
    const services = list(data.services);
    const healthy = services.filter(s => healthyStates.has(stateOf(s))).length;
    $('servicesKpi').replaceChildren(node('span', services.length ? healthy : '—'), node('small', '/ ' + (services.length || '—')));
    const unknown = services.filter(s => ['unknown', 'stale'].includes(stateOf(s))).length;
    $('servicesKpiDetail').textContent = services.length ? unknown ? `${unknown} état${unknown > 1 ? 's' : ''} à confirmer` :
      'Services actuellement observés' : 'État non mesuré';
    setWidth('servicesRule', services.length ? healthy / services.length : null);

    const scene = data.scene;
    const objects = scene ? list(scene.objects) : [];
    const snapshotAvailable = hasSceneSnapshot(scene);
    $('objectsKpi').textContent = snapshotAvailable ? number(objects.length) : '—';
    $('objectsKpiDetail').textContent = snapshotAvailable ?
      (finite(scene.frame) ? 'Instantané · frame ' + number(scene.frame) : 'Dernier instantané reçu') : 'Aucun instantané disponible';

    const capture = data.capture;
    const captured = capture?.captured;
    $('captureKpi').replaceChildren(node('span', number(captured)));
    if (finite(capture?.expected)) $('captureKpi').append(node('small', '/ ' + number(capture.expected)));
    $('captureKpiDetail').textContent = capture ?
      ((capture.historical || capture.kind === 'historical' ? 'Historique · ' : '') +
        (capture.outputName || capture.name || stateLabel(stateOf(capture)))) : 'Aucune campagne sélectionnée';
    setWidth('captureKpiBar', ratio(captured, capture?.expected));

    const vision = data.vision;
    const status = activityState(vision);
    $('visionKpi').replaceChildren();
    if (vision && finite(vision.completed)) {
      $('visionKpi').append(node('span', number(vision.completed)));
      if (finite(vision.expected)) $('visionKpi').append(node('small', '/ ' + number(vision.expected)));
    } else $('visionKpi').textContent = vision ? activityLabel(vision) : 'En attente';
    $('visionKpiDetail').textContent = vision ?
      (activeStates.has(status) && finite(vision.region) && finite(vision.regions) ?
        `Tuile ${vision.region}/${vision.regions} · ${vision.currentImage || 'RGB'}` : activityLabel(vision)) : 'Aucun traitement observé';
    setWidth('visionKpiBar', progress(vision));
  }

  function renderPreview(data) {
    const preview = data.preview;
    const url = safeURL(preview?.url);
    const previewAge = ageSeconds(preview?.updatedAt, preview?.ageSeconds);
    const live = !!preview && preview.live === true && preview.kind === 'live'
      && finite(previewAge) && previewAge <= 15;
    setBadge('previewBadge', url ? live ? 'running' : 'historical' : 'unknown', url ? live ? 'Aperçu récent' : 'Dernière image · historique' : 'Non disponible');
    const identity = url ? url + '|' + (preview.updatedAt || '') : '';
    if (identity !== previewIdentity) {
      previewIdentity = identity;
      if (url) {
        const imageURL = new URL(url, window.location.origin);
        if (preview.updatedAt) imageURL.searchParams.set('_frame', String(preview.updatedAt));
        $('unityPreview').src = imageURL.pathname + imageURL.search;
        $('unityPreview').hidden = false;
        $('previewEmpty').hidden = true;
      } else {
        $('unityPreview').removeAttribute('src');
        $('unityPreview').hidden = true;
        $('previewEmpty').hidden = false;
      }
    }
    $('previewOverlay').hidden = !url;
    const previewEngine=sourceEngine(preview);
    $('previewLabel').textContent = preview?.label || (live ? 'Rendu récemment observé' : 'Dernière capture disponible');
    if($('previewSourceEngine'))$('previewSourceEngine').textContent=previewEngine?'Source des images : '+previewEngine:'Source des images non mesurée';
    if($('previewTitle'))$('previewTitle').textContent=previewEngine?'Point de vue · '+previewEngine:'Point de vue du moteur 3D';
    $('previewAge').textContent = preview ? age(preview.updatedAt, preview.ageSeconds) : '';
    const renderer = data.renderer || data.unity, label=rendererLabel(data);
    $('unityScene').textContent = (label?label+' · ':'')+(renderer?.sceneName || renderer?.scene || 'Scène non observée');
    const playing = renderer?.isPlaying === true;
    const paused = renderer?.isPaused === true;
    const compiling = renderer?.isCompiling === true;
    const legacy=data.renderer?.type==='unity_legacy'||(!data.renderer&&!!data.unity),session=legacy?'Play':'Session';
    const unityStatus = renderer?.state || (renderer ? paused ? 'paused' : playing ? 'running' : 'idle' : 'unknown');
    const freshTelemetry = renderer && renderer.fresh !== false && !['unknown', 'stale'].includes(unityStatus);
    $('unityState').textContent = !renderer ? 'Moteur non mesuré' : !freshTelemetry ?
      unityStatus === 'unknown' ? session+' non mesuré'+(legacy?'':'e') : 'État de session ancien' :
      compiling ? 'Compilation'+(label?' · '+label:'') : paused ? session+' en pause' : playing ? session+' acti'+(legacy?'f':'ve') :
        renderer.isPlaying === false ? session+' arrêté'+(legacy?'':'e') : session+' non mesuré'+(legacy?'':'e');
    setDot('unityDot', unityStatus);
  }
  function renderServices(data) {
    const values = list(data.services);
    $('serviceCount').textContent = values.length ? values.length + ' composants' : '—';
    $('serviceList').replaceChildren();
    if (!values.length) { $('serviceList').append(node('div', 'Les vérifications locales vont apparaître ici.', 'empty-small')); return; }
    for (const service of values) {
      const state = stateOf(service);
      const row = node('div', null, 'service-row');
      const image = node('div', null, 'service-icon');
      image.append(icon(String(service.id).includes('unity') ? 'camera' : String(service.id).includes('ros') ? 'nodes' : String(service.id).includes('gazebo') ? 'ship' : 'grid'));
      const body = node('div');
      body.append(node('span', service.label || service.id || 'Service', 'service-name'));
      body.append(node('span', service.detail || service.evidence || 'Aucune preuve de vitalité disponible', 'service-detail'));
      const status = node('span', stateLabel(state), 'badge ' + tone(state));
      const evidence = [service.evidence, service.updatedAt ? 'Signal : ' + time(service.updatedAt, true) : null].filter(Boolean).join(' · ');
      if (evidence) row.title = evidence;
      row.append(image, body, status);
      $('serviceList').append(row);
    }
  }
  function renderAgents(data) {
    const agents = list(data.agents).slice().sort((a,b)=>Number(b.id==='scene_preparation')-Number(a.id==='scene_preparation'));
    const active = agents.filter(agent => activeStates.has(activityState(agent))).length;
    $('activeAgentCount').textContent = agents.length ? String(active) : '—';
    $('activeAgentCount').setAttribute('aria-label',agents.length?`${active} agents actifs sur ${agents.length} étapes`:'Activité des agents non mesurée');
    $('activeAgentCount').title=agents.length?`${active} en cours / ${agents.length} étapes observées`:'Activité non mesurée';
    setBadge('agentSummary', active ? 'running' : agents.length ? 'idle' : 'unknown',
      agents.length ? `${active} en cours / ${agents.length} étapes` : 'Non mesuré');
    $('overviewPipeline').replaceChildren();
    if (!agents.length) $('overviewPipeline').append(node('p', 'En attente de signaux de la chaîne.', 'empty-small'));
    const groups=[['preparation','Préparation'],['traffic','Trafic'],['rendering','Rendu & synchronisation'],['validation','Validation & rapports'],['other','Autres étapes']];
    let stageIndex=0;
    for(const [key,title] of groups){
      const values=agents.filter(agent=>agentGroup(agent)===key);if(!values.length)continue;
      const group=node('section',null,'pipeline-group');group.dataset.chainGroup=key;
      group.append(node('h3',title,'pipeline-group-title'));
      const stages=node('div',null,'pipeline-stages');
      for(const agent of values){
      const state = activityState(agent);
      const element = node('div', null, 'pipeline-node' + (activeStates.has(state) ? ' active' : ''));
      element.dataset.agentId=String(agent.id||'');
      const label = node('span', null, 'node-number'); label.append(dot(state), node('span', String(++stageIndex).padStart(2, '0')));
      element.append(label, node('h3', agentDisplayLabel(agent,data)), node('span', agent.id==='scene_preparation'?preparationLabel(agent):activityLabel(agent), 'node-state'));
      element.title = agent.detail || stateLabel(state);
      stages.append(element);
      }group.append(stages);$('overviewPipeline').append(group);
    }
    $('agentGrid').replaceChildren();
    if (!agents.length) $('agentGrid').append(node('div', 'Aucun état d’agent disponible. La présence d’un plan ancien ne prouve pas une activité courante.', 'empty-card'));
    for (const agent of agents) {
      const state = activityState(agent);
      const card = node('article', null, 'agent-card' + (activeStates.has(state) ? ' active' : '')+(agent.id==='scene_preparation'?' scene-preparation-card':''));
      card.dataset.agentId=String(agent.id||'');
      const heading = node('div', null, 'agent-card-head');
      const title = node('div'); title.append(node('div', agent.group || 'CHAÎNE LOCALE', 'agent-group'), node('h3', agentDisplayLabel(agent,data)));
      heading.append(title, node('span', agent.id==='scene_preparation'?preparationLabel(agent):activityLabel(agent), 'badge ' + tone(state)));
      card.append(heading, node('p', agent.detail || 'Aucune preuve d’activité courante disponible.'));
      if(agent.id==='scene_preparation')renderPreparationAgent(agent,card);
      card.append(node('div', agent.updatedAt ? age(agent.updatedAt) : 'Dernier signal non mesuré', 'agent-updated'));
      $('agentGrid').append(card);
    }
    renderJob('capture', data.capture);
    renderJob('vision', data.vision);
  }
  function agentGroup(agent){
    if(agent.id==='scene_preparation')return 'preparation';
    const group=String(agent.group||'').toLowerCase();
    if(['orchestrator','planner'].includes(agent.id)||/planification|trafic|traffic/.test(group))return 'traffic';
    if(['lotusim','renderer'].includes(agent.id)||/simulation|capture|rendu/.test(group))return 'rendering';
    if(['rgb_detector','proposal_reviewer','reporter'].includes(agent.id)||/vision|sortie|validation/.test(group))return 'validation';
    return 'other';
  }
  function agentDisplayLabel(agent,data){
    if(agent.id==='renderer')return 'Rendu'+(rendererLabel(data)?' · '+rendererLabel(data):' du moteur 3D');
    return agent.label||agent.id||'Étape';
  }
  function preparationLabel(agent){
    const state=activityState(agent);
    const label=state==='complete'||state==='completed'?'Fichiers préparés':state==='running'?'Préparation en cours':state==='failed'||state==='error'?'Préparation échouée':stateLabel(state);
    return label+(agent.historical===true&&state!=='historical'?' · historique':'');
  }
  function preparationURL(agent,value,filename){
    const id=agent.campaignId;
    if(typeof id!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(id))return null;
    const href=safeURL(value),expected='/api/settings/prepared/'+id+'/'+filename;
    return href===expected?href:null;
  }
  function renderPreparationAgent(agent,card){
    const engine=typeof agent.engineLabel==='string'?agent.engineLabel:typeof agent.engine==='string'?agent.engine.slice(0,120):'Non sélectionné';
    const facts=node('dl',null,'preparation-facts');
    facts.append(node('dt','Moteur ciblé'),node('dd',engine),node('dt',agent.historical===true?'Dernière campagne':'Campagne'),node('dd',typeof agent.campaignName==='string'?agent.campaignName.slice(0,240):agent.campaignId||'Aucune préparation observée'));
    card.append(facts);
    const roles=[['planner','Planification'],['scene_script_builder','Construction du script'],['validator','Vérification des fichiers']];
    const steps=node('ol',null,'preparation-steps');
    for(const [role,label] of roles){
      const step=list(agent.steps).find(item=>item?.role===role||item?.id===role)||{};
      let state=stateOf(step);
      if(!['idle','running','complete','completed','failed','stale','unknown'].includes(state))state='unknown';
      if(activeStates.has(state)&&!activeStates.has(activityState(agent)))state=activityState(agent)==='stale'?'stale':'idle';
      const item=node('li',null,'preparation-step');item.dataset.preparationRole=role;
      const heading=node('div',null,'preparation-step-heading');heading.append(dot(state),node('strong',label),node('span',stateLabel(state),'preparation-step-state'));
      item.append(heading,node('p',typeof step.detail==='string'?step.detail.slice(0,1200):'Aucun signal observé pour ce rôle.'));steps.append(item);
    }
    card.append(steps,node('p','Préparation de fichiers uniquement : cet agent ne lance aucun moteur, rendu natif ou annotation. Ses trois rôles sont déterministes, sans appel à un LLM.','preparation-scope'));
    const actions=node('div',null,'preparation-links'),settings=node('a','Ouvrir le paramétrage','text-link');settings.href='#settings';actions.append(settings);
    for(const [key,filename,label] of [['bundleUrl','bundle.zip','Bundle ZIP'],['manifestUrl','manifest.json','Manifeste'],['traceUrl','engine-agent.json','Trace des rôles']]){
      const href=preparationURL(agent,agent.links?.[key],filename);if(!href)continue;
      const link=node('a',label,'text-link');attachLink(link,href);actions.append(link);
    }card.append(actions);
  }
  function renderJob(kind, job) {
    const isVision = kind === 'vision';
    const status = activityState(job);
    if(!isVision&&$('captureSourceHeading'))$('captureSourceHeading').textContent=sourceEngine(job)?'CAPTURE · '+sourceEngine(job):'CAPTURE OBSERVÉE';
    setBadge(kind + 'Badge', status, activityLabel(job));
    const destination = $(kind + 'Details');
    destination.className = 'job-body';
    destination.replaceChildren();
    if (!job) { destination.append(node('div', isVision ? 'Aucun traitement observé.' : 'Aucune campagne observée.', 'empty-small')); return; }
    const done = isVision ? job.completed : job.captured;
    destination.append(node('div', finite(done) ? number(done) + (finite(job.expected) ? ' / ' + number(job.expected) : '') + (isVision ? ' images analysées' : ' captures') : stateLabel(status), 'job-main'));
    const bar = node('div', null, 'job-progress'), fill = node('span');
    const amount = isVision ? progress(job) : ratio(done, job.expected);
    fill.style.width = finite(amount) ? amount * 100 + '%' : '0%'; bar.append(fill); destination.append(bar);
    const facts = node('dl', null, 'job-facts');
    const values = isVision ? [
      ['Étape', activityLabel(job)], ['Image', job.currentImage || 'Non mesurée'],
      ['Tuilage', finite(job.region) && finite(job.regions) ? job.region + ' / ' + job.regions : 'Non mesuré'],
      ['Dernier signal', age(job.updatedAt, job.ageSeconds)],
    ] : [
      ['Campagne', job.outputName || job.name || baseName(job.outputDirectory) || 'Non mesurée'],
      ['Annotations', finite(job.boxes) ? number(job.boxes) + ' boîtes géométriques' : 'Non mesurées'],
      ['État', activityLabel(job)], ['Dernier signal', age(job.updatedAt, job.ageSeconds)],
    ];
    for (const [title, value] of values) facts.append(node('dt', title), node('dd', value));
    destination.append(facts);
  }

  function eventLevel(event) {
    const level = String(event.level || 'info').toLowerCase();
    return ['error', 'failed', 'fatal'].includes(level) ? 'error' : ['warning', 'warn'].includes(level) ? 'warning' : 'info';
  }
  function eventTone(event) { return eventLevel(event) === 'error' ? 'error' : eventLevel(event) === 'warning' ? 'warning' : 'neutral'; }
  function renderActivity(data) {
    const events = list(data.events).slice().sort((a, b) => (timestamp(b.at) || 0) - (timestamp(a.at) || 0));
    $('recentEvents').replaceChildren();
    if (!events.length) $('recentEvents').append(node('div', 'Aucun événement observé.', 'empty-small'));
    for (const event of events.slice(0, 5)) {
      const row = node('div', null, 'activity-item');
      const mark = node('span', null, 'status-dot ' + eventTone(event));
      const body = node('div');
      body.append(node('div', event.message || 'Événement sans message', 'activity-message'));
      body.append(node('div', [event.source || 'Source non précisée', event.historical ? 'historique' : 'signal observé'].join(' · '), 'activity-meta'));
      row.append(mark, body, node('time', event.at ? time(event.at) : '—', 'activity-time'));
      $('recentEvents').append(row);
    }
  }
  function renderJournal(data) {
    const events = list(data.events);
    const previous = $('eventSource').value;
    const sources = [...new Set(events.map(event => String(event.source || 'non précisée')))].sort();
    const existing = [...$('eventSource').options].slice(1).map(option => option.value);
    if (existing.join('|') !== sources.join('|')) {
      $('eventSource').replaceChildren(new Option('Toutes les sources', 'all'));
      for (const source of sources) $('eventSource').append(new Option(source, source));
      $('eventSource').value = sources.includes(previous) ? previous : 'all';
    }
    const source = $('eventSource').value, level = $('eventLevel').value;
    const query = $('eventSearch').value.trim().toLocaleLowerCase('fr-FR');
    const filtered = events.filter(event => (source === 'all' || String(event.source || 'non précisée') === source)
      && (level === 'all' || eventLevel(event) === level)
      && (!query || [event.source, event.message].filter(Boolean).join(' ').toLocaleLowerCase('fr-FR').includes(query)))
      .slice().sort((a, b) => (timestamp(a.at) || 0) - (timestamp(b.at) || 0));
    $('eventCount').textContent = `${filtered.length} événement${filtered.length > 1 ? 's' : ''}`;
    const rows = $('journalRows');
    const atBottom = rows.scrollHeight - rows.scrollTop - rows.clientHeight < 35;
    const newId = events.length ? String(events[events.length - 1].id || events[events.length - 1].at || events.length) : null;
    const changed = newId !== lastEventId;
    rows.replaceChildren();
    if (!filtered.length) rows.append(node('p', events.length ? 'Aucun événement ne correspond à ces filtres.' : 'Aucun événement disponible.', 'empty-small'));
    for (const event of filtered) {
      const row = node('div', null, 'journal-row');
      const clock = node('div', event.at ? time(event.at, true) : 'Non horodaté', 'journal-time');
      if (event.historical) clock.append(node('span', 'HISTORIQUE', 'historical-tag'));
      const origin = node('div', null, 'journal-source'); origin.append(node('span', null, 'status-dot ' + eventTone(event)), node('span', event.source || 'non précisée'));
      row.append(clock, origin, node('div', event.message || 'Événement sans message', 'journal-message'));
      rows.append(row);
    }
    if (changed && $('autoScroll').checked && (atBottom || lastEventId === null)) rows.scrollTop = rows.scrollHeight;
    lastEventId = newId;
  }

  function renderMap(data) {
    const scene = data.scene;
    const values = hasSceneSnapshot(scene) ? list(scene.objects).filter(object => finite(object.eastM) && finite(object.northM)).slice(0, 500) : [];
    const svg = $('sceneMap'); svg.replaceChildren();
    $('mapEmpty').hidden = values.length > 0;
    $('sceneFrame').textContent = scene && finite(scene.frame) ? 'Frame ' + number(scene.frame)
      + (scene.updatedAt ? ' · ' + age(scene.updatedAt) : '') : 'Pas de frame reçue';
    $('sceneTime').textContent = scene && finite(scene.timeSeconds) ? 'Temps simulé ' + number(scene.timeSeconds, 2) + ' s' : 'Positions en mètres';
    const north = svgNode('text', {x: 24, y: 28, fill: '#658ba3', 'font-size': 10, 'font-family': 'system-ui'});
    north.textContent = 'N'; svg.append(north, svgNode('path', {d: 'M28 50V35m-4 5 4-5 4 5', stroke: '#527d95', fill: 'none', 'stroke-width': 1.2}));
    const east = svgNode('text', {x: 559, y: 267, fill: '#658ba3', 'font-size': 9, 'font-family': 'system-ui'}); east.textContent = 'E'; svg.append(east);
    if (!values.length) return;
    const observer = values.find(object => String(object.id) === String(scene.observerId));
    const requested = $('mapRange').value;
    let centerEast, centerNorth, halfEast, halfNorth;
    if (requested !== 'all') {
      centerEast = observer ? observer.eastM : values.reduce((sum, object) => sum + object.eastM, 0) / values.length;
      centerNorth = observer ? observer.northM : values.reduce((sum, object) => sum + object.northM, 0) / values.length;
      halfNorth = Number(requested); halfEast = halfNorth * 2;
    } else {
      const eastValues = values.map(object => object.eastM), northValues = values.map(object => object.northM);
      const minEast = Math.min(...eastValues), maxEast = Math.max(...eastValues), minNorth = Math.min(...northValues), maxNorth = Math.max(...northValues);
      centerEast = (minEast + maxEast) / 2; centerNorth = (minNorth + maxNorth) / 2;
      halfNorth = Math.max(100, (maxNorth - minNorth) * .64, (maxEast - minEast) * .32); halfEast = halfNorth * 2;
    }
    const project = object => [300 + (object.eastM - centerEast) / halfEast * 260, 145 - (object.northM - centerNorth) / halfNorth * 118];
    let outside = 0;
    for (const object of values) {
      const [x, y] = project(object);
      if (x < 40 || x > 560 || y < 27 || y > 263) { outside++; continue; }
      const isObserver = observer === object;
      const airborne = finite(object.altitudeM) && object.altitudeM > 10;
      const color = isObserver ? '#edf4f9' : airborne ? '#baa6ed' : '#67d4bf';
      const circle = svgNode('circle', {cx: x, cy: y, r: isObserver ? 5 : 3.7, fill: color, stroke: '#0a1926', 'stroke-width': 1.2});
      const title = svgNode('title'); title.textContent = [object.id || 'Objet', object.model,
        finite(object.altitudeM) ? 'Altitude ' + number(object.altitudeM, 1) + ' m' : null].filter(Boolean).join(' · ');
      circle.append(title); svg.append(circle);
      if (isObserver) {
        svg.append(svgNode('circle', {cx: x, cy: y, r: 9, fill: 'none', stroke: '#9db5c8', 'stroke-opacity': .4, 'stroke-width': 1}));
        const label = svgNode('text', {x: x + 12, y: y + 3, fill: '#b1c6d6', 'font-size': 8, 'font-family': 'system-ui'}); label.textContent = 'Observateur'; svg.append(label);
      }
    }
    const scale = svgNode('text', {x: 45, y: 270, fill: '#678aa2', 'font-size': 8, 'font-family': 'system-ui'});
    const widthM = halfEast * 2;
    scale.textContent = 'Largeur ' + (widthM >= 1000 ? number(widthM / 1000, 1) + ' km' : number(widthM) + ' m') + (outside ? ' · ' + outside + ' hors cadre' : '');
    svg.append(scale);
  }

  function renderReports(data) {
    const reports = list(data.reports);
    $('reportCount').textContent = `${reports.length} rapport${reports.length > 1 ? 's' : ''}`;
    $('reportGrid').replaceChildren();
    if (!reports.length) $('reportGrid').append(node('div', 'Aucun rapport disponible. Les résultats produits apparaîtront ici sans démarrer automatiquement une analyse.', 'empty-card'));
    for (const report of reports) {
      const url = safeURL(report.url);
      const card = node(url ? 'a' : 'article', null, 'report-card');
      if (url) attachLink(card, url);
      const kind = node('div', null, 'report-kind'); kind.append(icon('files'), node('span', report.kind || 'Rapport local'));
      const action = node('div', url ? 'Ouvrir le rapport' : 'Lien non disponible', 'report-link'); action.append(icon('arrow'));
      card.append(kind, node('h3', report.label || report.name || 'Rapport sans titre'), node('p', report.updatedAt ? time(report.updatedAt, true) : 'Date non mesurée'), action);
      $('reportGrid').append(card);
    }
    const campaigns = list(data.campaigns);
    $('campaignCount').textContent = campaigns.length + ' campagne' + (campaigns.length > 1 ? 's' : '');
    $('campaignRows').replaceChildren();
    if (!campaigns.length) { const row = node('tr'), cell = node('td', 'Aucune campagne détectée.'); cell.colSpan = 5; row.append(cell); $('campaignRows').append(row); }
    for (const campaign of campaigns) {
      const row = node('tr');
      const name = node('td', campaign.name || campaign.id || 'Campagne');
      const state = node('td'); state.append(node('span', stateLabel(stateOf(campaign)), 'badge ' + tone(stateOf(campaign))));
      const capture = node('td', number(campaign.captured) + (finite(campaign.expected) ? ' / ' + number(campaign.expected) : ''));
      const date = node('td', campaign.updatedAt ? time(campaign.updatedAt, true) : 'Non mesuré');
      const action = node('td'), link = node('a', 'Rapport', 'table-link');
      if (attachLink(link, campaign.reportUrl)) { link.append(icon('arrow')); action.append(link); }
      else action.textContent = '—';
      row.append(name, state, capture, date, action); $('campaignRows').append(row);
    }
  }

  function render(data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Invalid state payload');
    current = data; lastSuccess = Date.now(); connectionFailed = false;
    document.body.classList.remove('loading');
    renderEngineProfile(data);renderKpis(data); renderPreview(data); renderServices(data); renderAgents(data);
    renderActivity(data); renderJournal(data); renderMap(data); renderReports(data);
    if (window.LotusimAlerts) {
      window.LotusimAlerts.update(data);
      $('globalNotice').hidden = true;
    } else {
      const messages = list(data.health?.warnings).filter(value => typeof value === 'string');
      if (data.health?.error) messages.unshift(String(data.health.error));
      $('globalNotice').hidden = !messages.length;
      $('globalNotice').textContent = messages.join(' · ');
    }
    $('footerSource').textContent = data.generatedAt ? 'État reçu à ' + time(data.generatedAt) + ' · sources locales' : 'Sources locales · heure non mesurée';
    updateConnection();
  }
  async function fetchState(manual = false) {
    if (fetchPending) return;
    fetchPending = true; $('refreshButton').disabled = true;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 6000);
    try {
      const response = await fetch('/api/state' + (manual ? '?refresh=1' : ''), {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const payload = await response.json();
      transportMode = 'http'; render(payload);
    } catch (_) {
      connectionFailed = true;
      if (!lastSuccess) {
        $('connectionText').textContent = 'Collecteur inaccessible';
        $('sideStatus').textContent = 'Aucune donnée reçue';
        setDot('sideDot', 'error');
        $('connection').querySelector('.status-dot').className = 'status-dot error';
        $('offlineNotice').hidden = false;
      }
      updateConnection();
    } finally { clearTimeout(timer); fetchPending = false; $('refreshButton').disabled = false; }
  }
  function connectEvents() {
    if (!('EventSource' in window)) return;
    eventSource = new EventSource('/api/events');
    eventSource.addEventListener('open', () => { eventStreamOpen = true; transportMode = 'sse'; updateConnection(); });
    const receive = event => {
      try { const payload = JSON.parse(event.data); eventStreamOpen = true; transportMode = 'sse'; render(payload); }
      catch (_) { eventStreamOpen = false; fetchState(); }
    };
    eventSource.addEventListener('state', receive);
    eventSource.addEventListener('message', receive);
    eventSource.addEventListener('error', () => { eventStreamOpen = false; updateConnection(); fetchState(); });
  }

  $('refreshButton').addEventListener('click', () => fetchState(true));
  for (const id of ['eventSource', 'eventLevel', 'eventSearch']) $(id).addEventListener(id === 'eventSearch' ? 'input' : 'change', () => { if (current) renderJournal(current); });
  $('autoScroll').addEventListener('change', () => { if ($('autoScroll').checked) $('journalRows').scrollTop = $('journalRows').scrollHeight; });
  $('mapRange').addEventListener('change', () => { if (current) renderMap(current); });
  $('unityPreview').addEventListener('error', () => {
    previewIdentity = '';
    $('unityPreview').hidden = true; $('previewEmpty').hidden = false;
    $('previewEmpty').querySelector('strong').textContent = 'Aperçu momentanément indisponible';
    setBadge('previewBadge', 'warning', 'Image indisponible');
  });
  window.addEventListener('hashchange', navigate);
  window.addEventListener('lotusim-engine-profile-updated',event=>{if(current&&event.detail){current={...current,engineProfile:event.detail};renderEngineProfile(current);}});
  document.body.classList.add('loading');
  navigate();
  const tick = () => {
    $('wallClock').textContent = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris', hour: '2-digit', minute: '2-digit', second: '2-digit'}).format(new Date());
    updateConnection();
    if (current?.preview) $('previewAge').textContent = age(current.preview.updatedAt, current.preview.ageSeconds);
  };
  tick(); setInterval(tick, 1000);
  fetchState(); connectEvents();
  setInterval(() => { if (!eventStreamOpen || Date.now() - lastSuccess > 4500) fetchState(); }, 2000);
  window.addEventListener('pagehide', () => { if (eventSource) eventSource.close(); });
})();

