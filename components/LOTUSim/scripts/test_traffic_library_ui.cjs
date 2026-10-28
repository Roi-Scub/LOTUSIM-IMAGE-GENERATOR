/* Deterministic traffic UI fixtures; no services, engines, ROS or real writes. */
'use strict';
const fs = require('node:fs'),
  path = require('node:path'),
  vm = require('node:vm'),
  assert = require('node:assert/strict');
const ui = path.resolve(process.argv[2] || path.join(__dirname, '../tools/ops_dashboard_ui')),
  math = require(path.join(ui, 'traffic.js'));
let checks = 0;
const check = (value, message) => {
    assert.ok(value, message);
    checks++;
  },
  near = (value, expected, message) => check(Math.abs(value - expected) < 1e-7, message);
const sea = {
  id: 'Sailboat_001',
  model: 'sailboat',
  category: 'sailboat',
  domain: 'sea',
  editable: true,
  startSeconds: 0,
  endSeconds: 60,
  centerSeconds: 30,
  centerENU: { eastM: 1000, northM: 0, altitudeM: 0 },
  speedMps: 5,
  maxSpeedMps: 10,
  maxAltitudeM: 0,
  headingDeg: 0,
  yawRateDegS: 0,
  boundedTurn: false,
  trajectoryKind: 'linear',
};
near(math.position(sea, 32).northM, 10, 'linear speed is in metres per second');
near(math.position(sea, 32).eastM, 1000, 'heading zero points north');
near(math.position({ ...sea, headingDeg: 90 }, 32).eastM, 1010, 'heading 90 points east');
near(math.position({ ...sea, headingDeg: 90 }, 32).northM, 0, 'east heading does not move north');
const turn = {
  ...sea,
  centerSeconds: 0,
  centerENU: { eastM: 0, northM: 0, altitudeM: 0 },
  speedMps: 10,
  yawRateDegS: 5,
  boundedTurn: true,
  turnStartSeconds: -2,
  turnEndSeconds: 2,
};
const w = (5 * Math.PI) / 180,
  at2 = math.position(turn, 2),
  at3 = math.position(turn, 3);
near(at2.eastM, (10 * (1 - Math.cos(2 * w))) / w, 'bounded turn integrates the east offset');
near(at2.northM, (10 * Math.sin(2 * w)) / w, 'bounded turn integrates the north offset');
near(
  at3.eastM - at2.eastM,
  10 * Math.sin(2 * w),
  'after a turn, velocity continues along the boundary tangent',
);
near(at3.northM - at2.northM, 10 * Math.cos(2 * w), 'post-turn speed remains continuous');
check(math.position(sea, NaN) === null, 'non-finite preview times are rejected');
const points = [
  { timeSeconds: 0, eastM: 0, northM: 0, altitudeM: 100 },
  { timeSeconds: 10, eastM: 20, northM: 10, altitudeM: 110 },
];
near(
  math.interpolate(points, 5).eastM,
  10,
  'original sampled trajectories interpolate without replacing their source',
);
near(
  math.interpolate(points, 20).altitudeM,
  110,
  'sampling beyond a presence interval clamps its preview endpoint',
);
const change = {
  actorId: sea.id,
  centerENU: { eastM: 100, northM: 200, altitudeM: 0 },
  speedMps: 7,
  headingDeg: 360,
};
check(math.validateChange(sea, change).headingDeg === 0, 'heading 360 normalizes to north');
for (const [actor, value, message] of [
  [sea, { ...change, speedMps: 11 }, 'speed cap'],
  [sea, { ...change, centerENU: { ...change.centerENU, altitudeM: 1 } }, 'sea altitude'],
  [{ ...sea, domain: 'moored', maxSpeedMps: 0 }, { ...change, speedMps: 1 }, 'moored speed'],
  [
    { ...sea, domain: 'air', maxAltitudeM: 120 },
    { ...change, centerENU: { ...change.centerENU, altitudeM: 0 } },
    'positive air altitude',
  ],
  [{ ...sea, editable: false }, change, 'read-only actor'],
  [sea, { ...change, centerENU: { ...change.centerENU, eastM: 100001 } }, 'coordinate bounds'],
]) {
  assert.throws(() => math.validateChange(actor, value), message);
  checks++;
}
const html = fs.readFileSync(path.join(ui, 'index.html'), 'utf8'),
  script = fs.readFileSync(path.join(ui, 'traffic.js'), 'utf8');
const css = fs.readFileSync(path.join(ui, 'traffic.css'), 'utf8');
const { hasCssDeclaration } = require('./source_contract_helpers.cjs');
check(
  ['sea', 'air', 'moored', 'observer'].every(
    (domain) =>
      html.includes('class="traffic-legend-' + domain + '"') &&
      hasCssDeclaration(css, '.traffic-legend-' + domain, 'background'),
  ) && !html.includes('<i style='),
  'map legend colors use CSP-compatible local CSS classes, not blocked inline styles',
);
check(
  html.includes('data-route="traffic"') && html.includes('src="/traffic.js"'),
  'traffic is a real local route and independent module',
);
check(
  !script.includes('innerHTML') && !script.includes('eval('),
  'traffic labels and source data are never interpreted as HTML or code',
);
check(
  !script.includes('/apply') && !script.includes('/launch'),
  'no live plan apply or simulation control route exists',
);
class Element {
  constructor(tag = 'div', id = '') {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.attributes = {};
    this.style = {};
    this.hidden = false;
    this.disabled = false;
    this._text = '';
    this._class = '';
    this.value = '';
    this.classList = { contains: (key) => this._class.split(' ').includes(key) };
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent || '').join('');
  }
  set className(value) {
    this._class = value;
  }
  get className() {
    return this._class;
  }
  append(...children) {
    this.children.push(...children);
  }
  replaceChildren(...children) {
    this.children = children;
    this._text = '';
  }
  setAttribute(key, value) {
    this.attributes[key] = String(value);
  }
  addEventListener(key, fn) {
    (this.listeners[key] ||= []).push(fn);
  }
  async dispatch(key) {
    for (const fn of this.listeners[key] || []) await fn({ target: this, preventDefault() {} });
  }
  click() {
    if (!this.disabled) return this.dispatch('click');
  }
}
const ids = Object.fromEntries(
  [...html.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], new Element('div', match[1])]),
);
ids.trafficMapView.value = 'all';
ids.trafficVersion.value = 'original';
ids.trafficDraftName.value = 'Brouillon contrôlé';
const air = {
  ...sea,
  id: 'Drone_001',
  model: 'small_drone',
  category: 'drone',
  domain: 'air',
  centerENU: { eastM: 300, northM: 400, altitudeM: 100 },
  speedMps: 30,
  maxSpeedMps: 60,
  maxAltitudeM: 120,
  headingDeg: 90,
};
const buoy = {
  ...sea,
  id: 'Buoy_001',
  model: 'buoy',
  category: 'buoy',
  domain: 'moored',
  centerENU: { eastM: 100, northM: 50, altitudeM: 0 },
  speedMps: 0,
  maxSpeedMps: 0,
};
const actors = [sea, air, buoy].map((actor) => ({
  ...actor,
  points: [0, 30, 60].map((at) => math.position(actor, at)),
}));
const plan = {
  schema: 'lotusim-traffic-editor-1',
  available: true,
  baseSha256: 'a'.repeat(64),
  source: {
    engineId: 'unity',
    label: 'Plan Unity existant',
    relativePath: 'Assets/Dataset/MaritimeTrafficAgents.plan.asset',
  },
  timeline: { startSeconds: 0, endSeconds: 60, durationSeconds: 60 },
  actors,
  observer: {
    id: 'ObserverBoat',
    model: 'fremm_observer',
    editable: false,
    points: [
      { timeSeconds: 0, eastM: 0, northM: 0, altitudeM: 0 },
      { timeSeconds: 60, eastM: 0, northM: 300, altitudeM: 0 },
    ],
  },
  warnings: ['Original safety approval does not apply to manually edited drafts.'],
  plan: { approved: true, events: [] },
  applied: false,
};
const originalSnapshot = JSON.stringify(plan),
  requests = [],
  windows = {};
let unavailable = false,
  conflict = false,
  unsafeLink = false,
  animationRequests = 0;
const draftId = 'b269d2da-662d-415c-8ea2-29127a51ffad';
let databaseMode = false,
  generationFailed = false,
  sequence = 0;
const records = [],
  database = new Map(),
  clone = (value) => JSON.parse(JSON.stringify(value));
function stored(name, kind, parentId = null, ready = true, preview = plan) {
  const id = '00000000-0000-4000-8000-' + String(++sequence).padStart(12, '0'),
    record = {
      id,
      name,
      kind,
      parentId,
      ready,
      auditStatus: ready ? 'approved' : 'requires_revalidation',
      actorCount: 3,
      durationSeconds: 60,
      createdAt: '2026-10-28T10:00:00Z',
      applied: false,
    };
  const value = {
    ...clone(preview),
    planId: id,
    record,
    audit: {
      approved: ready,
      fullColregCompliance: false,
      notCertified: true,
      limitations: ['Modèle borné, pas de certification de sûreté.'],
    },
  };
  records.unshift(record);
  database.set(id, value);
  return {
    id,
    planId: id,
    record,
    preview: value,
    files: ['plan.json', 'audit.json'],
    applied: false,
  };
}
const fetch = async (url, options = {}) => {
  requests.push({ url, options });
  if (url === '/api/traffic/plans')
    return {
      ok: true,
      json: async () => ({ schema: 'lotusim-traffic-library-1', plans: clone(records) }),
    };
  if (url.startsWith('/api/traffic/plan?planId='))
    return {
      ok: true,
      json: async () =>
        clone(database.get(new URL(url, 'http://localhost').searchParams.get('planId'))),
    };
  if (url === '/api/traffic/generate') {
    if (generationFailed)
      return {
        ok: false,
        status: 400,
        json: async () => ({
          errors: [
            { path: 'constraints', message: 'Contraintes incompatibles, aucun plan relâché.' },
          ],
        }),
      };
    const input = JSON.parse(options.body),
      result = stored(input.name, 'generated');
    return { ok: true, status: 201, json: async () => clone(result) };
  }
  if (/^\/api\/traffic\/plans\/.+\/revalidate$/.test(url)) {
    const parent = url.split('/')[4],
      result = stored('Contrôles réévalués', 'revalidation', parent, true, database.get(parent));
    return { ok: true, json: async () => clone(result) };
  }
  if (url === '/api/traffic/drafts' && databaseMode) {
    const input = JSON.parse(options.body),
      base = clone(database.get(input.planId));
    base.baseSha256 = 'c'.repeat(64);
    for (const change of input.changes) {
      const actor = base.actors.find((actor) => actor.id === change.actorId);
      Object.assign(actor, change);
      actor.points = actor.points.map((point) => math.position(actor, point.timeSeconds));
    }
    const result = stored(input.name, 'manual_revision', input.planId, false, base);
    return { ok: true, status: 201, json: async () => clone(result) };
  }
  if (url === '/api/traffic/plan')
    return {
      ok: true,
      json: async () =>
        unavailable
          ? { schema: plan.schema, available: false, warnings: ['Source absente.'] }
          : clone(plan),
    };
  if (url === '/api/traffic/drafts') {
    if (conflict)
      return {
        ok: false,
        status: 409,
        json: async () => ({ message: 'Le plan source a changé.' }),
      };
    return {
      ok: true,
      status: 201,
      json: async () => ({
        id: draftId,
        draft: { name: 'Brouillon contrôlé', requiresRevalidation: true },
        preview: { ...plan, draftPreview: true, requiresRevalidation: true },
        applied: false,
        downloadUrl: unsafeLink
          ? 'https://evil.example/draft.json'
          : '/api/traffic/drafts/' + draftId + '/draft.json',
      }),
    };
  }
  throw Error('Unexpected route ' + url);
};
const sandbox = {
  module: undefined,
  document: {
    getElementById: (id) => ids[id],
    createElement: (tag) => new Element(tag),
    createElementNS: (_, tag) => new Element(tag),
  },
  window: { confirm: () => true, addEventListener: (name, fn) => (windows[name] = fn) },
  location: { hash: '#traffic', origin: 'http://127.0.0.1:8766' },
  fetch,
  URL,
  Intl,
  Date,
  Number,
  Array,
  Object,
  Set,
  Map,
  Math,
  String,
  JSON,
  requestAnimationFrame: () => {
    animationRequests++;
    return 1;
  },
  cancelAnimationFrame: () => {},
};
const settle = () => new Promise(setImmediate),
  find = (root, test) =>
    [root, ...root.children.flatMap((child) => find(child, test))].filter(test);
(async () => {
  vm.runInNewContext(script, sandbox, { filename: 'traffic.js' });
  await settle();
  check(
    requests.length === 2 &&
      requests.some((item) => item.url === '/api/traffic/plan') &&
      requests.some((item) => item.url === '/api/traffic/plans') &&
      requests.every((item) => !item.options.method),
    'opening reads only the source plan and persistent library without generating or launching anything',
  );
  check(
    !ids.trafficWorkspace.hidden && ids.trafficObjects.children.length === 3,
    'source objects and workspace render',
  );
  check(
    ids.trafficSource.textContent.includes('Source : unity') &&
      ids.trafficSource.textContent.includes('Assets/Dataset/MaritimeTrafficAgents.plan.asset'),
    'plan provenance is explicit and independent of project profile',
  );
  check(
    ids.trafficSelectedTitle.textContent === 'Sailboat_001' &&
      ids.trafficSchedule.textContent.includes('0 à 60 s'),
    'selected model has its actual presence schedule',
  );
  check(
    find(ids.trafficMap, (item) => item.tagName === 'POLYLINE').length === 4 &&
      ids.trafficMap.textContent.includes('fremm_observer'),
    'map shows all object paths and the read-only observer',
  );
  ids.trafficTime.value = '15';
  await ids.trafficTime.dispatch('input');
  check(
    ids.trafficClock.textContent === '15 / 60 s' && requests.length === 2,
    'scrubbing updates local time without API writes',
  );
  await ids.trafficPlay.click();
  check(
    animationRequests === 1 &&
      ids.trafficPlay.textContent === 'Pause de l’aperçu' &&
      requests.length === 2,
    'playback requests only browser animation frames',
  );
  await ids.trafficPlay.click();
  ids.trafficEast.value = '200';
  ids.trafficNorth.value = '300';
  ids.trafficSpeed.value = '7';
  ids.trafficHeading.value = '90';
  await ids.trafficActorForm.dispatch('submit');
  check(
    ids.trafficVersion.value === 'working' &&
      ids.trafficDraftCount.textContent === '1 objet modifié' &&
      requests.length === 2,
    'manual edit first changes an unsaved local preview only',
  );
  check(
    ids.trafficDraftBadge.textContent === 'Brouillon non enregistré' &&
      ids.trafficNotice.textContent.includes('collisions'),
    'manual changes explicitly require a safety review',
  );
  check(
    JSON.stringify(plan) === originalSnapshot,
    'source plan and its original approval remain untouched',
  );
  await ids.trafficSave.click();
  const saved = requests.find((item) => item.url === '/api/traffic/drafts'),
    payload = JSON.parse(saved.options.body);
  check(
    saved.options.headers['X-LOTUSim-Traffic'] === '1' &&
      saved.options.headers['Content-Type'] === 'application/json',
    'immutable draft request has the exact local intent header',
  );
  check(
    Object.keys(payload).sort().join('|') === 'baseSha256|changes|name|planId' &&
      payload.planId === 'source' &&
      payload.baseSha256 === 'a'.repeat(64) &&
      payload.changes.length === 1,
    'only selected source ID, hash pin, name and explicit changes are sent, not a raw replacement plan',
  );
  check(
    payload.changes[0].actorId === sea.id &&
      payload.changes[0].speedMps === 7 &&
      payload.changes[0].centerENU.eastM === 200,
    'manual route parameters remain scoped to the selected actor',
  );
  check(
    ids.trafficDraftBadge.textContent === 'Brouillon enregistré · non appliqué' &&
      !ids.trafficSaved.hidden &&
      ids.trafficSavedLabel.textContent.includes('révalidation nécessaire'),
    'save never claims plan approval or live application',
  );
  check(
    ids.trafficExport.href === '/api/traffic/drafts/' + draftId + '/draft.json' &&
      !ids.trafficExport.hidden,
    'saved draft export link is scoped to its own immutable UUID',
  );
  ids.trafficSpeed.value = '100';
  const before = requests.length;
  await ids.trafficActorForm.dispatch('submit');
  check(
    requests.length === before && ids.trafficNotice.textContent.includes('vitesse'),
    'local speed-cap error does not create a request',
  );
  await ids.trafficObjects.children.find((item) => item.dataset.actorId === air.id).click();
  check(
    !ids.trafficAltitude.disabled && ids.trafficAltitude.max === '120',
    'air object has its own altitude capability',
  );
  ids.trafficAltitude.value = '0';
  await ids.trafficActorForm.dispatch('submit');
  check(
    ids.trafficNotice.textContent.includes('altitude aérienne'),
    'grounded airborne edits are rejected',
  );
  await ids.trafficObjects.children.find((item) => item.dataset.actorId === buoy.id).click();
  check(
    ids.trafficAltitude.disabled && ids.trafficSpeed.disabled && ids.trafficSpeed.value === '0',
    'moored object remains stationary at water reference',
  );
  await ids.trafficObjects.children.find((item) => item.dataset.actorId === sea.id).click();
  ids.trafficEast.value = '250';
  await ids.trafficActorForm.dispatch('submit');
  conflict = true;
  await ids.trafficSave.click();
  check(
    ids.trafficNotice.textContent.includes('plan source a changé') &&
      ids.trafficNotice.textContent.includes('conservées') &&
      ids.trafficDraftCount.textContent === '1 objet modifié',
    'SHA conflict preserves local edits rather than silently replacing the source',
  );
  conflict = false;
  unsafeLink = true;
  await ids.trafficSave.click();
  check(ids.trafficExport.hidden, 'external draft download URLs are rejected');
  ids.trafficSearch.value = 'small_drone';
  await ids.trafficSearch.dispatch('input');
  check(
    ids.trafficObjects.children.length === 1 &&
      ids.trafficObjects.textContent.includes('Drone_001'),
    'object search filters model metadata',
  );
  await ids.trafficResetAll.click();
  check(
    ids.trafficDraftCount.textContent === '0 objet modifié' &&
      ids.trafficVersion.value === 'original' &&
      ids.trafficSaved.hidden,
    'reset returns to original without deleting exported drafts',
  );
  unavailable = true;
  await ids.trafficReload.click();
  check(
    ids.trafficWorkspace.hidden &&
      !ids.trafficEmpty.hidden &&
      ids.trafficEmptyDetail.textContent === 'Source absente.',
    'unavailable source is explicit, never replaced with a fake generated scenario',
  );
  check(
    requests.every(
      (item) =>
        (['/api/traffic/plan', '/api/traffic/plans'].includes(item.url) && !item.options.method) ||
        (item.url === '/api/traffic/drafts' && item.options.method === 'POST'),
    ),
    'all legacy-editor requests are source/library reads or immutable-draft operations only',
  );
  databaseMode = true;
  unavailable = false;
  unsafeLink = false;
  await ids.trafficReload.click();
  ids.trafficGenerateName.value = 'Scénario coopératif test';
  ids.trafficGenerateSeed.value = '42';
  ids.trafficGenerateDuration.value = '60';
  ids.trafficGenerateProfile.value = 'crossing';
  await ids.trafficGenerateForm.dispatch('submit');
  const generateRequest = requests.findLast((item) => item.url === '/api/traffic/generate'),
    generatedId = records[0].id,
    generatedPayload = JSON.parse(generateRequest.options.body);
  check(
    generatedPayload.name === 'Scénario coopératif test' &&
      generatedPayload.seed === 42 &&
      generatedPayload.durationSeconds === 60 &&
      generatedPayload.actionProfile === 'crossing',
    'explicit generator sends name, seed, duration and action profile',
  );
  check(
    generateRequest.options.headers['X-LOTUSim-Traffic'] === '1' &&
      generateRequest.options.method === 'POST',
    'scenario generation is intent-scoped, never a read side effect',
  );
  check(
    !Object.hasOwn(generatedPayload, 'capture'),
    'default Traffic generation retains legacy scheduling by omitting capture',
  );
  check(
    ids.trafficPlanChoice.value === generatedId &&
      ids.trafficAuditBadge.textContent === 'Contrôles limités satisfaits',
    'new database plan is automatically selected and displayed with bounded audit status',
  );
  check(
    ids.trafficLibraryCount.textContent === '1 plans / révisions enregistrés' &&
      ids.trafficPlanExport.href === '/api/traffic/plans/' + generatedId + '/bundle.zip',
    'generated plan appears in the persistent library and has its scoped bundle',
  );
  check(
    ids.trafficAuditReasons.textContent.includes('pas de certification') &&
      html
        .replace(/\s+/g, ' ')
        .includes('Aucune certification de sûreté ni conformité COLREG complète'),
    'passing limited checks never becomes full COLREG or safety certification',
  );
  const storedGenerated = database.get(generatedId),
    originalWarnings = clone(storedGenerated.warnings),
    duplicateLimit = storedGenerated.audit.limitations[0];
  storedGenerated.warnings = [
    ...originalWarnings,
    duplicateLimit,
    duplicateLimit + ' (précision distincte)',
  ];
  ids.trafficPlanChoice.value = generatedId;
  await ids.trafficPlanChoice.dispatch('change');
  check(
    !ids.trafficWarnings.children.some((item) => item.textContent === duplicateLimit) &&
      ids.trafficAuditReasons.textContent.includes(duplicateLimit),
    'an exact audit limitation is displayed once, in the audit section rather than repeated among warnings',
  );
  check(
    ids.trafficWarnings.textContent.includes(originalWarnings[0]) &&
      ids.trafficWarnings.textContent.includes(duplicateLimit + ' (précision distincte)'),
    'different warnings and near-matching strings remain visible without approximate deduplication',
  );
  storedGenerated.warnings = originalWarnings;
  const generatedAudit = clone(database.get(generatedId).audit);
  database.get(generatedId).audit = {
    pairChecks: 528,
    checks: [{ a: 'Boat_A', b: 'Boat_B', safe: false, marginM: -2 }],
    errors: ['Geofence failed <img src=x>'],
    limitedColreg: {
      checks: [
        { rule: '14', passed: true },
        {
          rule: '15/16',
          passed: false,
          a: 'Boat_A',
          b: 'Boat_B',
          control: 'crossing_give_way_astern',
        },
      ],
      excludedPairs: [{}, {}, {}],
      fullColregCompliance: false,
    },
    limitations: ['Pas de conformité COLREG complète.'],
  };
  ids.trafficPlanChoice.value = generatedId;
  await ids.trafficPlanChoice.dispatch('change');
  check(
    ids.trafficAuditReasons.textContent.includes('528 séparations contrôlées') &&
      ids.trafficAuditReasons.textContent.includes('2 rencontres COLREG contrôlées') &&
      ids.trafficAuditReasons.textContent.includes('3 paires hors périmètre COLREG'),
    'real nested audit distinguishes separation count, limited encounter checks and excluded pairs',
  );
  check(
    ids.trafficAuditReasons.textContent.includes('Séparation non satisfaite · Boat_A · Boat_B') &&
      ids.trafficAuditReasons.textContent.includes('Marge : -2 m'),
    'failed separation pairs and finite margins are visible',
  );
  check(
    ids.trafficAuditReasons.textContent.includes(
      'Règle 15/16 · Boat_A · Boat_B · crossing_give_way_astern',
    ),
    'nested passed=false COLREG checks show the exact failed rule, actors and control',
  );
  check(
    ids.trafficAuditReasons.textContent.includes('Échec : Geofence failed <img src=x>') &&
      ids.trafficAuditReasons.children.every((item) => item.tagName === 'LI'),
    'top-level audit errors remain visible as safe text',
  );
  database.get(generatedId).audit = generatedAudit;
  await ids.trafficPlanChoice.dispatch('change');
  const baseHash = database.get(generatedId).baseSha256;
  ids.trafficEast.value = '1100';
  await ids.trafficActorForm.dispatch('submit');
  check(
    ids.trafficRevalidate.disabled,
    'unsaved changes must become an immutable revision before revalidation',
  );
  await ids.trafficSave.click();
  const revisionId = records[0].id,
    revisionRequest = JSON.parse(
      requests.findLast((item) => item.url === '/api/traffic/drafts').options.body,
    );
  check(
    revisionRequest.planId === generatedId && revisionRequest.baseSha256 === baseHash,
    'manual revision pins the selected database plan and its exact hash',
  );
  check(
    revisionId !== generatedId &&
      records[0].parentId === generatedId &&
      records[0].kind === 'manual_revision' &&
      ids.trafficPlanChoice.value === revisionId,
    'editing creates and selects a new child revision, not an in-place replacement',
  );
  check(
    ids.trafficAuditBadge.textContent === 'Révalidation nécessaire' &&
      !ids.trafficRevalidate.disabled &&
      ids.trafficPlanExport.textContent.includes('sans YAML'),
    'manual revision loses audit approval and only safe JSON/audit exports are advertised',
  );
  check(
    database.get(generatedId).baseSha256 === baseHash &&
      database.get(generatedId).actors[0].centerENU.eastM === 1000,
    'original approved database plan remains immutable',
  );
  const revisedHash = database.get(revisionId).baseSha256;
  await ids.trafficRevalidate.click();
  const auditId = records[0].id;
  check(
    records[0].kind === 'revalidation' &&
      records[0].parentId === revisionId &&
      auditId !== revisionId &&
      ids.trafficPlanChoice.value === auditId,
    'revalidation creates and selects a separate audit revision',
  );
  check(
    database.get(auditId).baseSha256 === revisedHash &&
      ids.trafficAuditBadge.textContent === 'Contrôles limités satisfaits',
    'revalidation keeps trajectories/hash while exposing only its limited result',
  );
  check(
    requests.findLast((item) => item.url.endsWith('/revalidate')).options.body === '{}',
    'revalidation cannot replace trajectories through arbitrary request fields',
  );
  records[0].name = '<img src=x onerror=alert(1)>';
  await ids.trafficLibraryRefresh.click();
  check(
    ids.trafficPlanChoice.textContent.includes('<img src=x onerror=alert(1)>') &&
      ids.trafficPlanChoice.children.every((item) => item.tagName === 'OPTION'),
    'library metadata is plain text, never interpreted HTML',
  );
  ids.trafficPlanChoice.value = 'source';
  await ids.trafficPlanChoice.dispatch('change');
  check(
    ids.trafficAuditBadge.textContent.includes('Source historique'),
    'legacy source remains separately selectable without being silently imported or replaced',
  );
  await ids.trafficLibraryRefresh.click();
  check(
    ids.trafficPlanChoice.children.length === 4,
    'refresh retrieves every persisted scenario/revision plus legacy source',
  );
  windows['lotusim-traffic-plan-selected']({ detail: { planId: generatedId } });
  await settle();
  check(
    ids.trafficPlanChoice.value === generatedId &&
      ids.trafficSource.textContent.includes('Plan Unity'),
    'settings-to-traffic event loads the generated database plan by ID',
  );
  generationFailed = true;
  await ids.trafficGenerateForm.dispatch('submit');
  check(
    ids.trafficNotice.textContent.includes('Contraintes incompatibles') &&
      ids.trafficPlanChoice.value === generatedId &&
      records.length === 3,
    'unsafe generator constraints are refused without silently replacing the current plan',
  );
  check(
    requests
      .filter((item) => item.options.method)
      .every(
        (item) => item.options.headers['X-LOTUSim-Traffic'] === '1' && !item.url.includes('/apply'),
      ),
    'all mutations are explicit generation, revisions or revalidation; never runtime application',
  );
  generationFailed = false;
  ids.trafficCaptureMode.value = 'interval';
  await ids.trafficCaptureMode.dispatch('change');
  ids.trafficCaptureInterval.value = '2';
  await ids.trafficCaptureInterval.dispatch('input');
  check(
    ids.trafficCapturePreview.textContent.includes('30 photos prévues') &&
      ids.trafficCapturePreview.textContent.includes('58 s simulées') &&
      ids.trafficCaptureCount.disabled,
    'Traffic interval preview includes t0, excludes the duration, and disables inactive count',
  );
  await ids.trafficGenerateForm.dispatch('submit');
  const cadenceInput = JSON.parse(
    requests.findLast((item) => item.url === '/api/traffic/generate').options.body,
  );
  check(
    cadenceInput.capture.mode === 'interval' && cadenceInput.capture.intervalSeconds === 2,
    'Traffic generation sends the explicitly chosen capture cadence',
  );
  const cadenceId = records[0].id,
    schedule = math.captureCadence(60, { mode: 'interval', intervalSeconds: 2 });
  database.get(cadenceId).captureSchedule = {
    schema: 'lotusim-capture-schedule-1',
    ...schedule,
    requestedIntervalSeconds: 2,
  };
  ids.trafficPlanChoice.value = cadenceId;
  await ids.trafficPlanChoice.dispatch('change');
  check(
    ids.trafficCaptureSchedule.textContent.includes(
      'Captures planifiées (non exécutées) : 30 photos',
    ) && ids.trafficCaptureSchedule.textContent.includes('58 s simulées'),
    'stored library schedule is shown as planned, not as executed image production',
  );
  ids.trafficCaptureInterval.value = '.01';
  await ids.trafficCaptureInterval.dispatch('input');
  const beforeInvalidCadence = requests.length;
  await ids.trafficGenerateForm.dispatch('submit');
  check(
    requests.length === beforeInvalidCadence &&
      ids.trafficNotice.textContent.includes('intervalle minimum'),
    'invalid cadence never creates a generation request',
  );
  console.log(checks + ' traffic-library generation and UI checks passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
