const { uiFile, coreRoot } = require('./support/paths.cjs');
/* Dependency-free DOM contract tests. Data here is explicitly a fixture. */
const fs = require('node:fs'),
  path = require('node:path'),
  vm = require('node:vm'),
  assert = require('node:assert/strict');
const ui = process.argv[2],
  html = fs.readFileSync(uiFile(ui, 'index.html'), 'utf8');
let checks = 0;
class Element {
  constructor(tag = 'div', id = '') {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.listeners = {};
    this._text = '';
    this._class = '';
    this.value = '';
    this.checked = false;
    this.hidden = false;
    this.disabled = false;
    this.scrollTop = 0;
    this.scrollHeight = 1000;
    this.clientHeight = 300;
    this.queries = {};
    this.classList = {
      add: (...values) => this._alter(values, []),
      remove: (...values) => this._alter([], values),
      toggle: (value, on) => {
        const set = new Set(this._class.split(' ').filter(Boolean));
        if (on === undefined) on = !set.has(value);
        on ? set.add(value) : set.delete(value);
        this._class = [...set].join(' ');
        return on;
      },
      contains: (value) => this._class.split(' ').includes(value),
    };
  }
  _alter(add, remove) {
    const set = new Set(this._class.split(' ').filter(Boolean));
    add.forEach((x) => set.add(x));
    remove.forEach((x) => set.delete(x));
    this._class = [...set].join(' ');
  }
  set className(value) {
    this._class = String(value);
  }
  get className() {
    return this._class;
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return (
      this._text + this.children.map((c) => (typeof c === 'string' ? c : c.textContent)).join('')
    );
  }
  append(...children) {
    this.children.push(...children);
  }
  replaceChildren(...children) {
    this._text = '';
    this.children = children;
  }
  setAttribute(key, value) {
    this.attributes[key] = String(value);
  }
  removeAttribute(key) {
    delete this.attributes[key];
  }
  addEventListener(key, listener) {
    (this.listeners[key] ||= []).push(listener);
  }
  dispatch(key, event = {}) {
    for (const fn of this.listeners[key] || []) fn({ target: this, ...event });
  }
  querySelector(key) {
    return (this.queries[key] ||= new Element(key === 'strong' ? 'strong' : 'span'));
  }
  get options() {
    return this.children;
  }
}
const ids = Object.fromEntries(
  [...html.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], new Element('div', match[1])]),
);
for (const id of ['eventSource', 'eventLevel']) ids[id].value = 'all';
ids.mapRange.value = 'all';
const nav = ['overview', 'agents', 'journal', 'reports'].map((route) => {
  const item = new Element('a');
  item.dataset.route = route;
  return item;
});
const body = new Element('body');
const doc = {
  body,
  activeElement: body,
  getElementById: (id) => {
    if (!ids[id]) throw Error('Unknown UI id ' + id);
    return ids[id];
  },
  createElement: (tag) => new Element(tag),
  createElementNS: (_, tag) => new Element(tag),
  querySelectorAll: (selector) => (selector === '[data-route]' ? nav : []),
};
const windows = {},
  location = { origin: 'http://127.0.0.1:8766', hash: '#overview' };
const now = new Date().toISOString();
const fixture = {
  schema: 'fixture',
  generatedAt: now,
  health: { warnings: [] },
  services: [
    { id: 'docker', label: 'Docker', state: 'ready', detail: 'fixture' },
    { id: 'unity', label: 'Unity', state: 'idle' },
    { id: 'ros', label: 'ROS', state: 'unknown' },
  ],
  unity: { sceneName: 'TestScene', isPlaying: false, state: 'idle' },
  preview: {
    url: '/files/fixture/f000000.png',
    kind: 'historical',
    live: false,
    updatedAt: '2020-01-01T00:00:00Z',
    label: 'Fixture historique',
  },
  capture: {
    status: 'complete',
    captured: 42,
    expected: 42,
    boxes: 84,
    historical: true,
    outputName: 'fixture-campaign',
    updatedAt: now,
  },
  vision: {
    status: 'detecting',
    completed: 2,
    expected: 12,
    currentImage: 'i000002.png',
    region: 4,
    regions: 16,
    updatedAt: now,
  },
  agents: [
    { id: 'planner', label: 'Planificateur', state: 'idle', group: 'Planification' },
    { id: 'detector', label: 'Détecteur RGB', state: 'running', group: 'Vision' },
  ],
  events: [
    {
      id: 'a',
      at: now,
      source: 'planner',
      level: 'info',
      message: 'Plan fixture',
      historical: true,
    },
    {
      id: 'b',
      at: now,
      source: 'detector',
      level: 'error',
      message: 'Erreur fixture',
      historical: false,
    },
  ],
  reports: [
    {
      id: 'r1',
      label: 'Rapport local',
      url: '/files/token/index.html',
      kind: 'vision',
      updatedAt: now,
    },
    { id: 'evil', label: 'Unsafe', url: 'https://evil.example/a' },
  ],
  campaigns: [
    {
      id: 'c1',
      name: 'Fixture',
      status: 'complete',
      captured: 42,
      expected: 42,
      reportUrl: '/files/token/index.html',
      updatedAt: now,
    },
  ],
  scene: {
    frame: 8,
    timeSeconds: 1.5,
    observerId: 'observer',
    objects: [
      { id: 'observer', model: 'fremm', eastM: 0, northM: 0, altitudeM: 0 },
      { id: 'bird', model: 'seagull', eastM: 100, northM: 150, altitudeM: 40 },
    ],
  },
};
class Events {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.listeners = {};
    Events.instances.push(this);
  }
  addEventListener(key, fn) {
    (this.listeners[key] ||= []).push(fn);
  }
  emit(key, data) {
    for (const fn of this.listeners[key] || []) fn({ data: JSON.stringify(data) });
  }
  close() {
    this.closed = true;
  }
}
const sandbox = {
  document: doc,
  location,
  window: { location, EventSource: Events, addEventListener: (key, fn) => (windows[key] = fn) },
  URL,
  Intl,
  Date,
  console,
  AbortController,
  Option: function (label, value) {
    const item = new Element('option');
    item.textContent = label;
    item.value = value;
    return item;
  },
  EventSource: Events,
  fetch: async () => ({ ok: true, json: async () => fixture }),
  setInterval: () => 1,
  setTimeout: () => 1,
  clearTimeout: () => {},
  Number,
  Array,
  Object,
  Set,
  Math,
  String,
  JSON,
};
function check(value, message) {
  assert.ok(value, message);
  checks++;
}
(async () => {
  vm.runInNewContext(fs.readFileSync(uiFile(ui, 'app.js'), 'utf8'), sandbox, {
    filename: 'app.js',
  });
  await new Promise(setImmediate);
  check(ids.servicesKpi.textContent === '1/ 3', 'services use only observed health');
  check(ids.objectsKpi.textContent === '2', 'objects count uses snapshot');
  check(ids.captureKpi.textContent === '42/ 42', 'capture count from fixture');
  check(ids.captureKpiDetail.textContent.startsWith('Historique'), 'historical capture identified');
  check(ids.visionKpi.textContent === '2/ 12', 'vision progress from fixture');
  check(
    ids.previewBadge.textContent.includes('historique'),
    'historical preview not labelled live',
  );
  check(ids.unityPreview.src.includes('_frame='), 'preview cache key uses observation timestamp');
  check(
    ids.reportGrid.children[0].tagName === 'A' && ids.reportGrid.children[1].tagName === 'ARTICLE',
    'only local report links enabled',
  );
  location.hash = '#agents';
  windows.hashchange();
  check(
    ids['page-overview'].hidden && !ids['page-agents'].hidden,
    'navigation switches real sections',
  );
  check(ids.agentGrid.children.length === 2, 'agents rendered');
  check(ids.activeAgentCount.textContent === '1', 'only running agent active');
  ids.eventLevel.value = 'error';
  ids.eventLevel.dispatch('change');
  check(ids.eventCount.textContent === '1 événement', 'level filter works');
  check(
    ids.journalRows.textContent.includes('Erreur fixture') &&
      !ids.journalRows.textContent.includes('Plan fixture'),
    'filtered messages only',
  );
  ids.eventSearch.value = 'not-found';
  ids.eventSearch.dispatch('input');
  check(ids.eventCount.textContent === '0 événement', 'search filter works');
  const stream = Events.instances[0];
  check(stream.url === '/api/events', 'SSE route');
  stream.emit('state', {
    ...fixture,
    preview: { ...fixture.preview, kind: 'live', live: true, updatedAt: new Date().toISOString() },
  });
  check(ids.previewBadge.textContent === 'Aperçu récent', 'fresh marked preview shown as recent');
  stream.emit('state', { ...fixture, preview: { ...fixture.preview, kind: 'live', live: true } });
  check(
    ids.previewBadge.textContent.includes('historique'),
    'stale claimed-live preview remains historical',
  );
  stream.emit('state', {
    ...fixture,
    unity: { state: 'unknown', fresh: false, isPlaying: null, isPaused: null, isCompiling: null },
    scene: {
      source: 'Unity / dernier instantané reçu',
      available: false,
      objects: [],
      frame: null,
      timeSeconds: null,
    },
    vision: { state: 'ready', status: 'complete', historical: true, completed: 12, expected: 12 },
    agents: [
      { id: 'planner', state: 'ready', detail: 'Plan déterministe archivé — pas un agent actif' },
      { id: 'orchestrator', state: 'ready', historical: true, detail: 'Plan enregistré' },
    ],
  });
  check(
    !ids.unityState.textContent.includes('Play arrêté'),
    'unknown Unity telemetry cannot claim Play stopped',
  );
  check(
    ids.objectsKpi.textContent === '—' &&
      ids.objectsKpiDetail.textContent === 'Aucun instantané disponible',
    'unavailable snapshot is not an observed empty scene',
  );
  check(
    ids.visionBadge.textContent === 'Terminé · historique',
    'raw complete job wins over normalized ready state',
  );
  check(
    ids.visionKpiDetail.textContent === 'Terminé · historique',
    'completed vision KPI identifies historical result',
  );
  check(
    !ids.agentGrid.textContent.includes('Disponible') &&
      ids.agentGrid.textContent.includes('Historique'),
    'archived planners are historical, not live available agents',
  );
  check(ids.activeAgentCount.textContent === '0', 'historical agents do not count as active');
  check(
    ids.serviceList.textContent.includes('Disponible'),
    'ready service retains available label',
  );
  stream.emit('state', {
    ...fixture,
    scene: { available: true, frame: 0, objects: [] },
    unity: { state: 'idle', fresh: true, isPlaying: false },
  });
  check(
    ids.objectsKpi.textContent === '0' && ids.objectsKpiDetail.textContent.includes('frame 0'),
    'valid empty snapshot shows measured zero',
  );
  check(
    ids.unityState.textContent === 'Play arrêté',
    'fresh explicitly false Play state remains stopped',
  );
  stream.emit('state', {
    ...fixture,
    scene: { objects: [], frame: null },
    unity: { state: 'unknown', isPlaying: null },
  });
  check(ids.objectsKpi.textContent === '—', 'unproven empty object list is not a snapshot');
  check(ids.unityState.textContent === 'Play non mesuré', 'unknown Unity state remains unmeasured');
  stream.emit('state', {
    schema: 'fixture-empty',
    generatedAt: new Date().toISOString(),
    health: {},
    services: [],
    agents: [],
    events: [],
    campaigns: [],
    reports: [],
    unity: null,
    preview: null,
    capture: null,
    vision: null,
    scene: null,
  });
  check(ids.objectsKpi.textContent === '—', 'missing snapshot not faked as objects');
  check(
    ids.previewEmpty.hidden === false && ids.unityPreview.hidden === true,
    'empty preview is explicit',
  );
  check(ids.agentGrid.textContent.includes('Aucun état'), 'empty agents explicit');
  check(ids.reportGrid.textContent.includes('Aucun rapport'), 'empty reports explicit');
  console.log(checks + ' behavior checks passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
