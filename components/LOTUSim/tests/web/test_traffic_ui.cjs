/* Deterministic traffic UI fixtures; no services, engines, ROS or real writes. */
'use strict';
const { uiFile, coreRoot } = require('./support/paths.cjs');
const fs = require('node:fs'),
  path = require('node:path'),
  vm = require('node:vm'),
  assert = require('node:assert/strict');
const ui = path.resolve(process.argv[2] || path.join(__dirname, '../../tools/ops_dashboard_ui')),
  math = require(uiFile(ui, 'traffic.js'));
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
const html = fs.readFileSync(uiFile(ui, 'index.html'), 'utf8'),
  script = fs.readFileSync(uiFile(ui, 'traffic.js'), 'utf8');
const css = fs.readFileSync(uiFile(ui, 'traffic.css'), 'utf8');
const { hasCssDeclaration } = require('./support/source_contract_helpers.cjs');
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
const fetch = async (url, options = {}) => {
  requests.push({ url, options });
  if (url === '/api/traffic/plans')
    return { ok: true, json: async () => ({ schema: 'lotusim-traffic-library-1', plans: [] }) };
  if (url === '/api/traffic/plan')
    return {
      ok: true,
      json: async () =>
        unavailable
          ? { schema: plan.schema, available: false, warnings: ['Source absente.'] }
          : JSON.parse(JSON.stringify(plan)),
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
  console.log(checks + ' traffic math and UI checks passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
