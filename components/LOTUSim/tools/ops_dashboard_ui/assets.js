'use strict';

(() => {
  if (typeof document === 'undefined') return;
  const root = document.getElementById('assetLibraryRoot');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const array = value => Array.isArray(value) ? value : [];
  const number = (value, digits = 1) => Number.isFinite(value)
    ? new Intl.NumberFormat('fr-FR', {maximumFractionDigits: digits}).format(value) : '—';
  const bytes = value => Number.isFinite(value) ? value < 1048576
    ? number(value / 1024, 0) + ' Ko' : number(value / 1048576, 1) + ' Mo' : '—';
  const categories = {
    buoy:'Bouée', bird:'Oiseau', drone:'Drone', airplane:'Avion', helicopter:'Hélicoptère',
    fishing_trawler:'Chalutier', container_ship:'Cargo', motor_yacht:'Yacht',
    speedboat:'Hors-bord', jetski:'Jet-ski', ferry:'Ferry', sailboat:'Voilier',
    observer:'Observateur', ship:'Navire', other:'Autre',
  };
  const geometryFormats = new Set(['glb', 'gltf', 'obj', 'stl']);
  const importCategories = ['buoy','bird','drone','airplane','helicopter','fishing_trawler','container_ship','motor_yacht','speedboat','jetski','ferry','sailboat','other'];
  const airborneCategories = new Set(['bird','drone','airplane','helicopter']);
  const mooredCategories = new Set(['buoy','other']);
  const integrationLabels = {queued:'En file d’attente',preparing:'Conversion en cours',waiting_unity:'En attente de Unity',failed:'Intégration interrompue',ready:'Disponible dans les scénarios'};
  let catalog = null, selected = null, loading = false, uploading = false, viewer = null;
  let viewerModule = null, selectionGeneration = 0, loadedPreview = false;
  let chosenFiles = [], integrating = false, editingIntegration = null;

  function node(tag, text, className) {
    const value = document.createElement(tag);
    if (text !== undefined && text !== null) value.textContent = String(text);
    if (className) value.className = className;
    return value;
  }
  function button(text, callback, className = 'secondary-button') {
    const value = node('button', text, className); value.type = 'button';
    value.addEventListener('click', callback); return value;
  }
  function option(value, label) {const result = node('option', label); result.value = value; return result;}
  function categoryLabel(category) {return categories[category] || String(category || 'Autre').replaceAll('_', ' ');}
  function labelFor(asset) {return asset.label || asset.model || asset.id || 'Modèle sans nom';}
  function imported(asset) {return /^import-[a-f0-9-]+$/.test(asset?.id || '');}
  function integrationState(asset) {
    const value = asset?.integration?.state;
    return Object.hasOwn(integrationLabels,value) ? value : imported(asset) ? 'queued' : null;
  }
  function integrationDefaults(category, upAxis) {
    return {metresPerUnit:1,forwardAxis:upAxis==='Z'?'+X':'+Z',draftM:0,
      maxSpeedMps:0,maxAltitudeM:airborneCategories.has(category)?120:0};
  }
  function previewIdentity(asset) {return JSON.stringify(asset?.preview || null);}
  function readyModels(value) {return array(value?.assets).filter(asset=>asset.integrationStatus==='integrated').map(asset=>asset.model).sort();}
  function safeURL(value, external = false) {
    if (typeof value !== 'string' || !value || value.includes('\\')) return null;
    try {
      const result = new URL(value, location.origin);
      if (!['http:', 'https:'].includes(result.protocol)) return null;
      if (!external && result.origin !== location.origin) return null;
      return external ? result.href : result.pathname + result.search;
    } catch (_) {return null;}
  }
  function notice(message, kind = '') {
    $('assetLibraryNotice').hidden = !message;
    $('assetLibraryNotice').textContent = message;
    $('assetLibraryNotice').className = 'notice assets-notice' + (kind ? ' ' + kind : '');
  }
  function glyph(category) {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 100 60'); svg.setAttribute('aria-hidden', 'true');
    const shapes = {
      buoy:['M42 21h16l6 28H36z', 'M45 10h10v11H45z', 'M50 4v6M33 52h34M45 30h10'],
      bird:['M7 35q17-24 42-3Q74 9 93 35M49 32v9M44 41h10'],
      drone:['M38 28h24v10H38z', 'M27 17l15 12m16 0 15-12M27 48l15-12m16 0 15 12', 'M16 17h22M62 17h22M16 48h22M62 48h22'],
      airplane:['M51 7l6 24 33 10v5L57 41l-2 11h12v4H35v-4h12l-3-11-34 5v-5l34-10 3-24z'],
      helicopter:['M24 30h44l12 9-10 8H30l-7-8-16-9V19l11 15', 'M47 30V18M16 18h66M35 51h35M40 47v4m21-4v4'],
      sailboat:['M11 45h78L77 56H25z', 'M49 6v39M45 12 22 40h23zM54 17l24 23H54z'],
      container_ship:['M9 36h83L81 53H24z', 'M27 16h15v20H27zM45 16h15v20H45zM63 16h15v20H63zM14 23h10v13H14z'],
      fishing_trawler:['M12 38h77L73 54H26z', 'M28 22h31v16H28zM36 13h15v9M68 12v26m0-23 17 19M29 29h24'],
      ferry:['M8 39h84L79 54H23z', 'M19 19h57l9 20H17zM29 13h30v6M27 27h5m7 0h5m7 0h5m7 0h5'],
      jetski:['M16 38h64L63 48H31z', 'M38 30h22l10 8M39 26l7 5'],
      default:['M11 38h79L75 53H27z', 'M34 24h27l17 14H30zM42 18h13v6M42 30h12'],
    };
    for (const d of shapes[category] || shapes.default) {
      const path = document.createElementNS(ns, 'path'); path.setAttribute('d', d); svg.append(path);
    }
    return svg;
  }
  function field(labelText, control, help) {
    const label = node('label', null, 'assets-field'); label.append(node('span', labelText), control);
    if (help) label.append(node('small', help)); return label;
  }
  function input(id, type = 'text') {const result = node('input'); result.id = id; result.type = type; return result;}
  function addFact(list, title, value) {list.append(node('dt', title), node('dd', value));}
  async function getJSON(url, options) {
    const response = await fetch(url, options);
    let body; try {body = await response.json();} catch (_) {throw Error('Réponse locale illisible. Réessayez après avoir vérifié le dashboard.');}
    if (!response.ok) throw Error(body.error || 'La bibliothèque locale est indisponible.');
    return body;
  }

  function build() {
    const toolbar = node('div', null, 'section-toolbar assets-toolbar');
    const heading = node('div'); heading.append(node('h2', 'Bibliothèque de modèles 3D'),
      node('p', 'Inspecter la géométrie disponible, retrouver ses sources et ajouter de nouvelles variantes.', 'muted'));
    const actions = node('div', null, 'assets-toolbar-actions');
    const reload = button('Actualiser', () => refresh()); reload.id = 'assetReload';
    const add = button('+ Ajouter un modèle', openUpload, 'primary-button'); add.id = 'assetAdd';
    actions.append(reload, add); toolbar.append(heading, actions);
    const message = node('div', null, 'notice assets-notice'); message.id = 'assetLibraryNotice';
    message.setAttribute('role', 'status'); message.hidden = true;
    const stats = node('div', null, 'assets-stats');
    for (const [id, title, detail] of [
      ['assetTotal', 'MODÈLES LOCAUX', 'Géométries et variantes du catalogue'],
      ['assetIntegrated', 'INTÉGRÉS AU PIPELINE', 'Disponibles pour les campagnes existantes'],
      ['assetPending', 'IMPORTS EN INTÉGRATION', 'Prêts seulement après confirmation de Unity et LOTUSim'],
    ]) {
      const article = node('article', null, 'assets-stat'); const value = node('strong', '—'); value.id = id;
      article.append(node('span', title), value, node('small', detail)); stats.append(article);
    }
    const workspace = node('div', null, 'assets-workspace');
    const library = node('article', null, 'panel assets-library');
    const filters = node('div', null, 'assets-filters');
    const search = input('assetSearch', 'search'); search.placeholder = 'Nom du modèle, catégorie…';
    search.addEventListener('input', renderGrid);
    const category = node('select'); category.id = 'assetCategory'; category.append(option('all', 'Toutes les catégories'));
    category.addEventListener('change', renderGrid);
    const status = node('select'); status.id = 'assetStatus';
    status.append(option('all', 'Tous les statuts'), option('integrated', 'Intégrés'),
      option('available_mesh', 'Meshes historiques'), option('imported_pending', 'Importés à préparer'));
    status.addEventListener('change', renderGrid);
    filters.append(field('Rechercher', search), field('Catégorie', category), field('Intégration', status));
    const resultLine = node('div', null, 'assets-result-line'); const count = node('span', 'Chargement…'); count.id = 'assetResultCount';
    resultLine.append(count, node('span', 'Sélectionner pour inspecter', 'muted'));
    const grid = node('div', null, 'assets-grid'); grid.id = 'assetGrid'; grid.setAttribute('aria-label', 'Modèles disponibles');
    library.append(filters, resultLine, grid);

    const inspector = node('article', null, 'panel assets-inspector');
    const inspectorHead = node('div', null, 'panel-heading');
    const selectedHeading = node('div'); selectedHeading.append(node('span', 'INSPECTION GÉOMÉTRIQUE', 'section-kicker'));
    const name = node('h2', 'Choisir un modèle'); name.id = 'assetSelectedName'; selectedHeading.append(name);
    const format = node('span', '3D', 'badge neutral'); format.id = 'assetSelectedFormat'; inspectorHead.append(selectedHeading, format);
    const stage = node('div', null, 'assets-preview-stage'); stage.id = 'meshPreviewStage';
    stage.setAttribute('aria-label', 'Prévisualisation 3D interactive du modèle sélectionné');
    const previewMessage = node('div', null, 'assets-preview-message'); previewMessage.id = 'meshViewerState';
    previewMessage.setAttribute('role', 'status');
    previewMessage.append(glyph('default'), node('strong', 'Les modèles sont chargés à la demande'),
      node('span', 'Choisis une carte dans la bibliothèque pour ouvrir sa géométrie.'));
    const previewWrap = node('div', null, 'assets-preview-wrap'); previewWrap.append(stage, previewMessage);
    const previewControls = node('div', null, 'assets-preview-controls');
    const instruction = node('span', 'Glisser : pivoter · molette : zoomer');
    const meshStats = node('span', '', 'assets-mesh-stats'); meshStats.id = 'meshPreviewStats';
    const reset = button('Recentrer', () => viewer?.reset()); reset.id = 'meshReset'; reset.disabled = true;
    const wireLabel = node('label', null, 'assets-wireframe'); const wire = input('meshWireframe', 'checkbox');
    wire.disabled = true; wire.addEventListener('change', () => viewer?.setWireframe(wire.checked));
    wireLabel.append(wire, node('span', 'Maillage')); previewControls.append(instruction, meshStats, reset, wireLabel);
    const body = node('div', null, 'assets-inspector-body'); body.id = 'assetDetails';
    body.append(node('p', 'Aperçu de la géométrie uniquement : ce n’est pas un rendu natif de simulation ni une mesure de physique.', 'assets-help'));
    inspector.append(inspectorHead, previewWrap, previewControls, body); workspace.append(library, inspector);
    const footnote = node('p', 'Adaptateur de bibliothèque actuellement opérationnel : Unity / LOTUSim. Les imports sont convertis localement puis intégrés lorsque le bon projet Unity est ouvert, hors Play. Ils apparaissent après confirmation du prefab, de sa clé Addressables et du modèle LOTUSim. Changer de profil moteur ne crée pas automatiquement un importeur natif pour les autres moteurs. Aucun lancement de simulation.', 'assets-help assets-bottom-note');
    root.append(toolbar, message, stats, workspace, footnote, buildUpload(), buildIntegrationDialog());
  }

  function renderStats() {
    const assets = array(catalog?.assets);
    $('assetTotal').textContent = number(assets.length, 0);
    $('assetIntegrated').textContent = number(assets.filter(asset => asset.integrationStatus === 'integrated').length, 0);
    $('assetPending').textContent = number(assets.filter(asset => asset.integrationStatus === 'imported_pending').length, 0);
    const categoriesSeen = [...new Set(assets.map(asset => asset.category).filter(Boolean))].sort((a,b) => categoryLabel(a).localeCompare(categoryLabel(b), 'fr'));
    const previous = $('assetCategory').value;
    $('assetCategory').replaceChildren(option('all', 'Toutes les catégories'), ...categoriesSeen.map(category => option(category, categoryLabel(category))));
    $('assetCategory').value = categoriesSeen.includes(previous) ? previous : 'all';
    const uploadCategory = $('assetUploadCategory'); const uploadPrevious = uploadCategory.value;
    uploadCategory.replaceChildren(...importCategories
      .sort((a,b) => categoryLabel(a).localeCompare(categoryLabel(b), 'fr')).map(category => option(category, categoryLabel(category))));
    uploadCategory.value = importCategories.includes(uploadPrevious) ? uploadPrevious : 'other';
    $('assetUploadLimit').textContent = 'GLB conseillé pour réunir géométrie et textures. Limite totale : ' +
      bytes(catalog?.limits?.maxUploadBytes || 67108864) + ', ' + number(catalog?.limits?.maxFiles || 100, 0) + ' fichiers. Aucun ZIP ni script.';
  }
  function renderGrid() {
    const all = array(catalog?.assets), term = $('assetSearch').value.trim().toLocaleLowerCase('fr');
    const category = $('assetCategory').value, status = $('assetStatus').value;
    const visible = all.filter(asset => (category === 'all' || asset.category === category)
      && (status === 'all' || asset.integrationStatus === status)
      && (!term || [labelFor(asset),asset.model,asset.category,categoryLabel(asset.category)].join(' ').toLocaleLowerCase('fr').includes(term)));
    $('assetResultCount').textContent = number(visible.length, 0) + ' / ' + number(all.length, 0) + ' modèles';
    const grid = $('assetGrid'); grid.replaceChildren();
    if (!visible.length) {
      const empty = node('div', null, 'assets-grid-empty');
      empty.append(node('strong', all.length ? 'Aucun modèle pour ces filtres' : 'Aucun modèle local disponible'),
        node('p', all.length ? 'Essaye un autre nom ou une autre catégorie.' : 'Ajoute un modèle ou vérifie le catalogue du projet.'));
      grid.append(empty); return;
    }
    for (const asset of visible) {
      const card = button('', () => selectAsset(asset), 'assets-card' + (asset.id === selected?.id ? ' selected' : ''));
      card.dataset.assetId = asset.id; card.setAttribute('aria-pressed', String(asset.id === selected?.id));
      const visual = node('span', null, 'assets-card-visual'); visual.append(glyph(asset.category));
      visual.append(node('span', String(asset.preview?.format || 'source').toUpperCase(), 'assets-card-format'));
      const title = node('strong', labelFor(asset));
      const state = integrationState(asset);
      const statusNode = node('span', asset.integrationStatus === 'integrated' ? 'Intégré'
        : asset.integrationStatus === 'available_mesh' ? 'Mesh disponible' : integrationLabels[state] || 'À préparer',
        'assets-card-status ' + (asset.integrationStatus === 'integrated' ? 'ready'
          : asset.integrationStatus === 'available_mesh' ? 'historical' : state==='failed'?'failed':'pending'));
      card.append(visual, node('span', categoryLabel(asset.category), 'assets-card-category'), title,
        node('span', (Number.isFinite(asset.dimensions?.lengthM) ? number(asset.dimensions.lengthM, 1) + ' m · ' : '') + bytes(asset.bytes), 'assets-card-measures'), statusNode);
      grid.append(card);
    }
  }
  function renderDetails(asset) {
    $('assetSelectedName').textContent = labelFor(asset);
    $('assetSelectedFormat').textContent = String(asset.preview?.format || 'source').toUpperCase();
    const body = $('assetDetails'); body.replaceChildren();
    const status = node('div', null, 'assets-status-row');
    status.append(node('span', asset.integrationStatus === 'integrated' ? 'Intégré au pipeline'
      : asset.integrationStatus === 'available_mesh' ? 'Source historique · intégration à vérifier' : 'Importé · préparation requise',
      'badge ' + (asset.integrationStatus === 'integrated' ? 'live'
        : asset.integrationStatus === 'available_mesh' ? 'neutral' : 'warning')),
      node('span', categoryLabel(asset.category), 'assets-category-label'));
    const description = node('p', asset.integrationStatus === 'integrated'
      ? 'Les campagnes existantes connaissent ce modèle. L’aperçu montre sa géométrie, pas son rendu final dans un moteur 3D.'
      : asset.integrationStatus === 'available_mesh'
      ? 'Cette géométrie provient des modèles historiques du projet. Sa présence ne prouve pas qu’un prefab Unity et une configuration de campagne compatibles sont prêts : leur intégration reste à vérifier.'
      : 'L’intégration se fait automatiquement en arrière-plan. Le modèle ne sera proposé dans le paramétrage qu’après confirmation du prefab Unity et de son enregistrement LOTUSim.', 'assets-help');
    const dimensions = node('div', null, 'assets-dimensions');
    for (const [key,label] of [['lengthM','Longueur'],['beamM','Largeur'],['heightM','Hauteur']]) {
      const metric = node('div'); metric.append(node('span',label), node('strong', Number.isFinite(asset.dimensions?.[key]) ? number(asset.dimensions[key], 2) + ' m' : '—')); dimensions.append(metric);
    }
    const facts = node('dl', null, 'assets-facts');
    addFact(facts, 'Identifiant', asset.model || asset.id);
    addFact(facts, 'Domaine', ({sea:'Maritime',air:'Aérien',moored:'Amarré / flottant'})[asset.domain] || asset.domain || 'À définir');
    addFact(facts, 'Fichiers', number(asset.fileCount, 0) + ' · ' + bytes(asset.bytes));
    addFact(facts, 'Axe vertical de l’aperçu', asset.preview?.upAxis || 'Non précisé');
    addFact(facts, 'Licence déclarée', asset.license || 'Non renseignée — vérifier avant utilisation');
    body.append(status, description, dimensions, facts);
    if (imported(asset)) body.append(renderIntegration(asset));
    const link = safeURL(asset.sourceUrl, true);
    if (link) {
      const source = node('a', 'Consulter la source et ses conditions ↗', 'assets-source-link');
      source.href = link; source.target = '_blank'; source.rel = 'noopener noreferrer'; body.append(source);
    }
    if (asset.notes) body.append(node('p', asset.notes, 'assets-note'));
    body.append(node('p', 'Les dimensions du catalogue et la licence déclarée sont des informations de provenance ; cet aperçu ne certifie ni l’échelle, ni les droits d’usage, ni le comportement physique.', 'assets-help assets-provenance-note'));
  }
  function renderIntegration(asset) {
    const state = integrationState(asset), section = node('section',null,'assets-integration-panel '+state);
    const heading = node('div',null,'assets-integration-heading');
    heading.append(node('span',null,'assets-integration-dot'),node('h3',integrationLabels[state]||'Intégration automatique'));
    section.append(heading);
    const fallback = state==='waiting_unity'
      ? 'Ouvrir le projet Unity de ce dossier et laisser Play arrêté. La création du prefab reprendra automatiquement ; aucune activation de licence n’est effectuée par le dashboard.'
      : state==='queued' ? 'Les fichiers sont enregistrés ; leur conversion locale va commencer.'
      : state==='preparing' ? 'Vérification de la géométrie, des unités et des matériaux, puis préparation du paquet Unity.'
      : state==='ready' ? 'Le prefab et le modèle LOTUSim sont enregistrés. Cet objet est maintenant disponible dans Paramétrage.'
      : 'Le modèle n’est pas disponible dans les scénarios. Corriger les paramètres ou le fichier puis relancer l’intégration.';
    section.append(node('p',asset.integration?.message||fallback,'assets-help'));
    if(state==='waiting_unity' && asset.integration?.message) section.append(node('p',fallback,'assets-help'));
    const steps=node('ol',null,'assets-integration-steps');
    for(const [index,label] of ['Fichiers','Conversion','Adaptateur Unity','Catalogue'].entries()){
      const reached=state==='ready'?4:state==='waiting_unity'?2:state==='failed'?0:1;
      steps.append(node('li',label,index<reached?'done':index===reached&&state!=='failed'?'current':''));
    }
    section.append(steps);
    const options=asset.integration?.options;
    if(options){
      const facts=node('dl',null,'assets-facts assets-integration-facts');
      addFact(facts,'Unité du fichier',number(options.metresPerUnit,4)+' m / unité');
      addFact(facts,'Avant du modèle',options.forwardAxis||'Non précisé');
      addFact(facts,'Vitesse maximale déclarée',number(options.maxSpeedMps,2)+' m/s');
      if(airborneCategories.has(asset.category))addFact(facts,'Altitude maximale déclarée',number(options.maxAltitudeM,0)+' m');
      section.append(facts);
    }
    const commands=node('div',null,'assets-integration-actions');
    if(state==='ready'){
      const link=node('a','Utiliser dans le paramétrage →','assets-scenario-link');link.href='#settings';commands.append(link);
    }
    const action=button(state==='failed'?'Corriger et relancer':'Paramètres d’intégration',()=>openIntegration(asset));
    action.disabled=integrating||state==='preparing';commands.append(action);section.append(commands);
    section.append(node('p','Les limites de déplacement sont déclaratives, non certifiées. La réponse à la houle est une approximation visuelle, pas une calibration hydrodynamique.','assets-help assets-integration-disclaimer'));
    return section;
  }
  function previewState(title, detail, error = false) {
    const message = $('meshViewerState'); message.hidden = false;
    message.className = 'assets-preview-message' + (error ? ' error' : '');
    message.replaceChildren(glyph(selected?.category), node('strong', title), node('span', detail));
  }
  function disposeViewer() {selectionGeneration++; viewer?.dispose(); viewer = null; loadedPreview = false;}
  async function selectAsset(asset, loadHeavy = false) {
    disposeViewer(); selected = asset; renderGrid(); renderDetails(asset);
    const generation = selectionGeneration;
    $('meshReset').disabled = true; $('meshWireframe').disabled = true; $('meshWireframe').checked = false;
    $('meshPreviewStats').textContent = '';
    const preview = asset.preview;
    if (!preview || (!safeURL(preview.url) && preview.format !== 'sdf')) {
      previewState('Aperçu 3D non disponible', 'La source est répertoriée, mais aucune géométrie compatible n’est accessible pour ce modèle.'); return;
    }
    if (asset.bytes > 24 * 1048576 && !loadHeavy) {
      previewState('Modèle détaillé · ' + bytes(asset.bytes), 'Ce modèle comporte des fichiers volumineux. Son chargement 3D ne démarre qu’à ta demande.');
      $('meshViewerState').append(button('Charger l’aperçu 3D', () => selectAsset(asset, true), 'primary-button assets-load-heavy'));
      return;
    }
    previewState('Chargement du mesh local', 'La géométrie est chargée à la demande, sans lancer de moteur 3D ni LOTUSim.');
    try {
      viewerModule ||= await import('/mesh-viewer.js');
      if (generation !== selectionGeneration || location.hash !== '#assets') return;
      const currentViewer = new viewerModule.MeshPreview($('meshPreviewStage')); viewer = currentViewer;
      const result = await currentViewer.load(preview);
      if (generation !== selectionGeneration || viewer !== currentViewer) {currentViewer.dispose(); return;}
      loadedPreview = true; $('meshViewerState').hidden = true;
      $('meshReset').disabled = false; $('meshWireframe').disabled = false;
      if (Number.isFinite(result?.triangles)) $('meshPreviewStats').textContent = number(result.triangles, 0) + ' triangles';
      if (array(result?.warnings).length) $('assetDetails').append(node('p', result.warnings.join(' · '), 'assets-note'));
    } catch (error) {
      if (generation !== selectionGeneration) return;
      viewer?.dispose(); viewer = null;
      previewState('Impossible d’afficher ce mesh', error.message || 'Vérifiez le fichier et ses dépendances de matériaux.', true);
    }
  }
  async function refresh(selectId, options = {}) {
    if (loading) return;
    loading = true; $('assetReload').disabled = true; if(!options.silent)notice('');
    if (!catalog) $('assetGrid').replaceChildren(node('p','Lecture du catalogue local…','assets-grid-empty'));
    try {
      const next = await getJSON('/api/assets/catalog');
      if (next.schema !== 'lotusim-mesh-library-1' || !Array.isArray(next.assets)) throw Error('Le format du catalogue n’est pas reconnu.');
      const previousReady=JSON.stringify(readyModels(catalog));
      const unchanged=JSON.stringify(next.assets)===JSON.stringify(catalog?.assets);
      catalog = next;
      if(!unchanged){renderStats();renderGrid();}
      const nextAsset = next.assets.find(asset => asset.id === (selectId || selected?.id)) || next.assets[0];
      if (nextAsset && location.hash === '#assets') {
        if(options.preservePreview && selected?.id===nextAsset.id && previewIdentity(selected)===previewIdentity(nextAsset)){
          selected=nextAsset;if(!unchanged)renderDetails(nextAsset);
        }else await selectAsset(nextAsset);
      }
      if(previousReady!==JSON.stringify(readyModels(next)))window.dispatchEvent(new CustomEvent('lotusim-assets-updated',{detail:{readyModels:readyModels(next)}}));
    } catch (error) {if(!options.silent)notice(error.message, 'error');}
    finally {loading = false; $('assetReload').disabled = false;}
  }

  function buildUpload() {
    const dialog = node('dialog', null, 'assets-upload-dialog'); dialog.id = 'assetUploadDialog';
    dialog.setAttribute('aria-labelledby','assetUploadTitle');
    const form = node('form'); form.id = 'assetUploadForm'; form.addEventListener('submit', submitUpload);
    const header = node('div', null, 'assets-upload-heading'); const title = node('h2', 'Ajouter un modèle local'); title.id = 'assetUploadTitle';
    const close = button('Fermer', () => {if (!uploading) dialog.close();}); close.id = 'assetUploadClose'; header.append(title, close);
    const intro = node('p', 'Importer le mesh et ses dépendances via l’adaptateur de bibliothèque Unity / LOTUSim actuellement disponible. La conversion puis la création du prefab et du modèle LOTUSim sont automatiques ; le projet Unity doit être ouvert hors Play. Aucun autre moteur n’est installé ou intégré par ce formulaire.', 'assets-help');
    const fields = node('div', null, 'assets-upload-fields');
    const name = input('assetUploadName'); name.required = true; name.maxLength = 120; name.placeholder = 'Ex. voilier de croisière — variante 2';
    const category = node('select'); category.id = 'assetUploadCategory'; category.append(...importCategories.map(key => option(key,categories[key]))); category.value = 'other';
    const license = input('assetUploadLicense'); license.required = true; license.maxLength = 300; license.placeholder = 'Ex. CC0, CC-BY 4.0, création personnelle…';
    const source = input('assetUploadSource', 'url'); source.maxLength = 1000; source.placeholder = 'https://… (facultatif)';
    const axis = node('select'); axis.id = 'assetUploadAxis'; axis.append(option('Y', 'Y — convention Unity / glTF'), option('Z', 'Z — convention Gazebo'));
    category.addEventListener('change',()=>updateIntegrationControls('assetUpload',category.value,axis.value,true));
    axis.addEventListener('change',()=>updateIntegrationControls('assetUpload',category.value,axis.value));
    fields.append(field('Nom du modèle',name),field('Catégorie',category),field('Licence / droits déclarés',license),field('Page source du modèle',source),field('Axe vertical',axis,'Changer l’axe de l’aperçu ne certifie pas l’échelle du modèle.'));
    const fileArea = node('div',null,'assets-upload-file-area');
    const files = input('assetUploadFiles','file'); files.multiple = true;
    files.accept = '.glb,.gltf,.obj,.stl,.mtl,.bin,.png,.jpg,.jpeg,.webp,.tga,.bmp'; files.required = true;
    files.addEventListener('change', () => updateFiles([...files.files]));
    const fileLabel = field('Mesh et fichiers associés',files,'Sélectionner le mesh ainsi que son .mtl, ses textures ou ses buffers si le format en dépend.');
    const directory = input('assetUploadDirectory','file'); directory.multiple = true; directory.hidden = true;
    directory.setAttribute('webkitdirectory','');
    directory.addEventListener('change', () => {
      const accepted = [...directory.files].filter(file => /\.(?:glb|gltf|obj|stl|mtl|bin|png|jpe?g|webp|tga|bmp)$/i.test(file.name));
      files.value = ''; updateFiles(accepted);
    });
    const folderButton = button('Choisir un dossier avec ses textures', () => directory.click());
    const folderHelp = node('p','Le dossier conserve les chemins relatifs des sous-dossiers de textures. Les documents et formats non pris en charge sont ignorés.','assets-help');
    const limit = node('p', 'GLB conseillé. Limite totale : 64 Mo, 100 fichiers. Aucun ZIP ni script.', 'assets-help'); limit.id = 'assetUploadLimit';
    const list = node('ul', null, 'assets-upload-file-list'); list.id = 'assetUploadFileList';
    const entry = node('select'); entry.id = 'assetUploadEntry'; entry.required = true; entry.append(option('','Choisir d’abord les fichiers'));
    fileArea.append(fileLabel, folderButton, directory, folderHelp, limit, list, field('Mesh principal',entry,'Un import représente un modèle, même s’il comporte plusieurs fichiers de matériaux.'));
    const confirm = node('label',null,'assets-upload-rights'); const rights = input('assetUploadRights','checkbox'); rights.required = true;
    confirm.append(rights,node('span','Je dispose des droits nécessaires pour importer ces fichiers et j’ai vérifié leurs conditions d’utilisation.'));
    const warning = node('div',null,'notice assets-notice'); warning.id = 'assetUploadNotice'; warning.hidden = true; warning.setAttribute('role','status');
    const actions = node('div',null,'assets-upload-actions'); const status = node('span','Les fichiers restent sur ce Mac.','assets-help'); status.id='assetUploadStatus';
    const submit = node('button','Importer dans la bibliothèque','primary-button'); submit.type='submit'; submit.id='assetUploadSubmit'; actions.append(status,submit);
    form.append(header,intro,fields,buildIntegrationFields('assetUpload','other','Y'),fileArea,confirm,warning,actions); dialog.append(form);
    dialog.addEventListener('cancel',event=>{if(uploading)event.preventDefault();}); return dialog;
  }
  function updateFiles(files) {
    chosenFiles = files;
    $('assetUploadFiles').required = !files.length;
    const list = $('assetUploadFileList'); list.replaceChildren();
    for (const file of files) list.append(node('li',(file.webkitRelativePath||file.name)+' · '+bytes(file.size)));
    const entry = $('assetUploadEntry'); entry.replaceChildren();
    const meshes = files.filter(file=>geometryFormats.has(file.name.split('.').at(-1).toLowerCase()));
    if (!meshes.length) entry.append(option('','Sélectionner un GLB, GLTF, OBJ ou STL'));
    else entry.append(...meshes.map(file=>option(file.webkitRelativePath||file.name,file.webkitRelativePath||file.name)));
    if (meshes.length === 1 && !$('assetUploadName').value) $('assetUploadName').value=meshes[0].name.replace(/\.[^.]+$/,'').replaceAll('_',' ');
    const total = files.reduce((sum,file)=>sum+file.size,0);
    $('assetUploadStatus').textContent=files.length ? number(files.length,0)+' fichiers · '+bytes(total)+' à importer' : 'Les fichiers restent sur ce Mac.';
  }
  function openUpload() {
    const dialog = $('assetUploadDialog'); $('assetUploadNotice').hidden=true;
    if (!dialog.open) dialog.showModal();
    $('assetUploadName').focus();
  }
  function numericInput(id,value,min,max,step='any'){
    const valueInput=input(id,'number');valueInput.required=true;valueInput.min=String(min);valueInput.max=String(max);valueInput.step=step;
    valueInput.value=String(value);valueInput.defaultValue=String(value);return valueInput;
  }
  function buildIntegrationFields(prefix,category,upAxis,options={}){
    const values={...integrationDefaults(category,upAxis),...options};
    const section=node('section',null,'assets-integration-fields');
    section.append(node('h3','Préparation via l’adaptateur Unity / LOTUSim'),node('p','L’échelle et les capacités ne peuvent pas être déduites avec certitude du mesh. Vérifier ces valeurs avant génération ; 1 unité = 1 mètre par défaut, vitesse inconnue = 0.','assets-help'));
    const grid=node('div',null,'assets-integration-grid');
    const scale=numericInput(prefix+'Scale',values.metresPerUnit,.0001,1000);
    const forward=node('select');forward.id=prefix+'Forward';forward.required=true;
    for(const axis of ['+X','-X','+Y','-Y','+Z','-Z'])if(!axis.endsWith(upAxis))forward.append(option(axis,axis));forward.value=values.forwardAxis;
    if(!forward.value)forward.value=integrationDefaults(category,upAxis).forwardAxis;
    const draft=numericInput(prefix+'Draft',values.draftM,0,25);
    const speed=numericInput(prefix+'MaxSpeed',values.maxSpeedMps,0,350);
    const altitude=numericInput(prefix+'MaxAltitude',values.maxAltitudeM,0,15000);
    grid.append(field('Mètres par unité du fichier',scale,'Ex. 0,01 pour un mesh exprimé en centimètres.'),
      field('Axe vers l’avant',forward,'L’avant est converti vers +X dans le prefab ; l’axe vertical est défini ci-dessus.'),
      field('Tirant d’eau visuel (m)',draft,'De 0 à 25 m, sans dépasser la hauteur du modèle. Maritime uniquement : approximation de ligne de flottaison, pas une mesure de stabilité.'),
      field('Vitesse maximale déclarée (m/s)',speed,'Limite du scénario, non certifiée. 0 garde l’objet immobile.'),
      field('Altitude maximale déclarée (m)',altitude,'Aérien uniquement. Limite du scénario, non certifiée.'));
    draft.disabled=mooredCategories.has(category)||airborneCategories.has(category);
    speed.disabled=mooredCategories.has(category);altitude.disabled=!airborneCategories.has(category);
    section.append(grid);return section;
  }
  function updateIntegrationControls(prefix,category,upAxis,categoryChanged=false){
    const forward=$(prefix+'Forward');if(!forward)return;
    const previous=forward.value;forward.replaceChildren(...['+X','-X','+Y','-Y','+Z','-Z'].filter(axis=>!axis.endsWith(upAxis)).map(axis=>option(axis,axis)));
    forward.value=previous;if(!forward.value)forward.value=integrationDefaults(category,upAxis).forwardAxis;
    const airborne=airborneCategories.has(category),moored=mooredCategories.has(category);
    $(prefix+'Draft').disabled=airborne||moored;if(airborne||moored)$(prefix+'Draft').value='0';
    $(prefix+'MaxSpeed').disabled=moored;if(moored)$(prefix+'MaxSpeed').value='0';
    $(prefix+'MaxAltitude').disabled=!airborne;
    if(!airborne)$(prefix+'MaxAltitude').value='0';else if(categoryChanged&&Number($(prefix+'MaxAltitude').value)===0)$(prefix+'MaxAltitude').value='120';
  }
  function integrationOptions(prefix){
    return {metresPerUnit:Number($(prefix+'Scale').value),forwardAxis:$(prefix+'Forward').value,
      draftM:Number($(prefix+'Draft').value),maxSpeedMps:Number($(prefix+'MaxSpeed').value),maxAltitudeM:Number($(prefix+'MaxAltitude').value)};
  }
  function buildIntegrationDialog(){
    const dialog=node('dialog',null,'assets-upload-dialog');dialog.id='assetIntegrationDialog';dialog.setAttribute('aria-labelledby','assetIntegrationTitle');
    const form=node('form');form.id='assetIntegrationForm';form.addEventListener('submit',submitIntegration);
    const header=node('div',null,'assets-upload-heading'),title=node('h2','Paramètres d’intégration');title.id='assetIntegrationTitle';
    const close=button('Fermer',()=>{if(!integrating)dialog.close();});close.id='assetIntegrationClose';header.append(title,close);
    const intro=node('p','Une modification prépare une nouvelle révision. L’objet peut temporairement disparaître du catalogue jusqu’à confirmation de Unity, hors Play. Les campagnes ne sont jamais lancées ici.','assets-help');
    const body=node('div');body.id='assetIntegrationBody';
    const message=node('div',null,'notice assets-notice');message.id='assetIntegrationNotice';message.hidden=true;message.setAttribute('role','status');
    const actions=node('div',null,'assets-upload-actions'),submit=node('button','Préparer et relancer','primary-button');submit.type='submit';submit.id='assetIntegrationSubmit';actions.append(node('span','Catégorie et fichiers d’origine conservés.','assets-help'),submit);
    form.append(header,intro,body,message,actions);dialog.append(form);dialog.addEventListener('cancel',event=>{if(integrating)event.preventDefault();});return dialog;
  }
  function openIntegration(asset){
    editingIntegration=asset;$('assetIntegrationTitle').textContent='Intégrer · '+labelFor(asset);
    $('assetIntegrationNotice').hidden=true;
    $('assetIntegrationBody').replaceChildren(buildIntegrationFields('assetIntegration',asset.category,asset.preview?.upAxis||'Y',asset.integration?.options));
    $('assetIntegrationDialog').showModal();
  }
  async function submitIntegration(event){
    event.preventDefault();if(integrating||!editingIntegration)return;
    integrating=true;$('assetIntegrationSubmit').disabled=true;$('assetIntegrationClose').disabled=true;$('assetIntegrationNotice').hidden=true;
    try{
      const id=editingIntegration.id;
      await getJSON('/api/assets/'+encodeURIComponent(id)+'/integrate',{method:'POST',headers:{'X-LOTUSim-Asset-Import':'1','Content-Type':'application/json'},body:JSON.stringify({options:integrationOptions('assetIntegration')})});
      $('assetIntegrationDialog').close();await refresh(id,{preservePreview:true});
      notice('Préparation demandée. Le catalogue des scénarios sera actualisé après confirmation de Unity, hors Play.','success');
    }catch(error){$('assetIntegrationNotice').textContent=error.message;$('assetIntegrationNotice').hidden=false;$('assetIntegrationNotice').className='notice assets-notice error';}
    finally{integrating=false;$('assetIntegrationSubmit').disabled=false;$('assetIntegrationClose').disabled=false;}
  }
  function uploadNotice(message,kind='error') {
    $('assetUploadNotice').textContent=message; $('assetUploadNotice').hidden=!message;
    $('assetUploadNotice').className='notice assets-notice '+kind;
  }
  async function submitUpload(event) {
    event.preventDefault(); if(uploading)return;
    const files=chosenFiles, total=files.reduce((sum,file)=>sum+file.size,0), limit=catalog?.limits?.maxUploadBytes||67108864;
    if(!files.length)return uploadNotice('Choisir au moins un mesh compatible.');
    if(files.length>(catalog?.limits?.maxFiles||100))return uploadNotice('Le nombre de fichiers dépasse la limite de cet import.');
    if(total>=limit)return uploadNotice('Les fichiers atteignent la limite de '+bytes(limit)+'. L’enveloppe d’import doit aussi pouvoir tenir dans cette limite.');
    if(!$('assetUploadEntry').value)return uploadNotice('Choisir un mesh principal au format GLB, GLTF, OBJ ou STL.');
    const metadata={name:$('assetUploadName').value.trim(),category:$('assetUploadCategory').value,
      license:$('assetUploadLicense').value.trim(),sourceUrl:$('assetUploadSource').value.trim(),
      upAxis:$('assetUploadAxis').value,entryFile:$('assetUploadEntry').value,
      integrationOptions:integrationOptions('assetUpload')};
    const body=new FormData(); body.append('metadata',JSON.stringify(metadata));
    for(const file of files)body.append('files',file,file.webkitRelativePath||file.name);
    uploading=true; uploadNotice('');
    $('assetUploadSubmit').disabled=true; $('assetUploadClose').disabled=true;
    $('assetUploadStatus').textContent='Import local et validation des fichiers…';
    try {
      const result=await getJSON('/api/assets/import',{method:'POST',headers:{'X-LOTUSim-Asset-Import':'1'},body});
      if(!result.asset?.id)throw Error('Le serveur n’a pas confirmé l’ajout du modèle.');
      $('assetUploadDialog').close(); $('assetUploadForm').reset(); updateFiles([]);
      updateIntegrationControls('assetUpload','other','Y');
      await refresh(result.asset.id);
      notice('Fichiers enregistrés. L’intégration Unity / LOTUSim est mise en file automatiquement ; le modèle apparaîtra dans Paramétrage une fois prêt.','success');
    } catch(error){uploadNotice(error.message||'Import non confirmé. Vérifiez le catalogue avant de réessayer.');}
    finally{uploading=false; $('assetUploadSubmit').disabled=false; $('assetUploadClose').disabled=false;
      if(!$('assetUploadDialog').open)$('assetUploadStatus').textContent='Les fichiers restent sur ce Mac.';}
  }
  async function enter() {
    if(location.hash==='#assets') {
      if(!catalog)await refresh();
      else await refresh(selected?.id,{preservePreview:!!viewer,silent:true});
    } else if(viewer||loadedPreview)disposeViewer();
  }
  build(); window.addEventListener('hashchange',enter); window.addEventListener('ops-route',enter); enter();
  setInterval(()=>{
    if(location.hash==='#assets'&&!document.hidden&&!uploading&&!integrating&&!loading
      &&array(catalog?.assets).some(asset=>['queued','preparing','waiting_unity'].includes(integrationState(asset))))
      refresh(selected?.id,{preservePreview:true,silent:true});
  },3000);
})();
