/* Frozen journal/export contracts, using explicit local fixtures only. No server. */
'use strict';
const { uiFile, coreRoot } = require('./support/paths.cjs');
const fs = require('node:fs'),
  path = require('node:path'),
  vm = require('node:vm'),
  assert = require('node:assert/strict');
const ui = process.argv[2] || path.join(__dirname, '../../tools/ops_dashboard_ui');
const html = fs.readFileSync(uiFile(ui, 'index.html'), 'utf8'),
  script = fs.readFileSync(uiFile(ui, 'app.js'), 'utf8');
let checks = 0,
  fetches = 0;
const downloads = [],
  blobs = new Map(),
  timers = [],
  created = [];
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
    this.replacements = 0;
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
    this.replacements++;
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
  click() {
    if (this.tagName === 'A') downloads.push({ href: this.href, name: this.download });
    else this.dispatch('click');
  }
  remove() {
    this.removed = true;
  }
}
const identifiers = new Set([...html.matchAll(/id="([^"]+)"/g)].map((match) => match[1]));
// Parent owns the markup; literal app targets permit running this fixture while
// that parallel edit is being completed. The static UI suite checks real IDs.
for (const match of script.matchAll(/\$\('([A-Za-z0-9_-]+)'\)/g)) identifiers.add(match[1]);
const ids = Object.fromEntries([...identifiers].map((id) => [id, new Element('div', id)]));
for (const id of ['eventSource', 'eventLevel']) ids[id].value = 'all';
ids.mapRange.value = 'all';
const body = new Element('body'),
  windows = {},
  location = { origin: 'http://127.0.0.1:8766', hash: '#journal' };
const nav = ['overview', 'agents', 'traffic', 'journal', 'reports', 'settings', 'assets'].map(
  (route) => {
    const e = new Element('a');
    e.dataset.route = route;
    return e;
  },
);
const doc = {
  body,
  activeElement: body,
  getElementById: (id) => {
    assert.ok(ids[id], 'unknown id ' + id);
    return ids[id];
  },
  createElement: (tag) => {
    const e = new Element(tag);
    created.push(e);
    return e;
  },
  createElementNS: (_, tag) => new Element(tag),
  querySelectorAll: (selector) => (selector === '[data-route]' ? nav : []),
};
class LocalURL extends URL {
  static createObjectURL(blob) {
    const key = 'blob:fixture-' + blobs.size;
    blobs.set(key, blob);
    return key;
  }
  static revokeObjectURL(key) {
    LocalURL.revoked.push(key);
  }
}
LocalURL.revoked = [];
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
  emit(data) {
    for (const fn of this.listeners.state || []) fn({ data: JSON.stringify(data) });
  }
  close() {
    this.closed = true;
  }
}
const stamp = (offset) =>
  new Date(Date.parse('2026-10-28T12:00:00Z') + offset * 1000).toISOString();
const a = {
  id: 'a',
  at: stamp(0),
  source: 'planner',
  level: 'info',
  message: 'Plan de référence',
  historical: true,
};
const b = {
  id: 'b',
  at: stamp(10),
  source: 'vision',
  level: 'error',
  message: 'Erreur contrôlée',
  historical: false,
};
const c = {
  id: 'c',
  at: stamp(20),
  source: 'new-source',
  level: 'warning',
  message: 'Nouveau message',
  historical: false,
};
const fixture = {
  generatedAt: stamp(30),
  health: { warnings: [] },
  services: [],
  agents: [],
  events: [b, a],
  reports: [],
  campaigns: [],
  capture: { status: 'capturing', captured: 2, expected: 9, historical: false },
  scene: null,
  preview: null,
  unity: null,
  vision: null,
};
const sandbox = {
  document: doc,
  location,
  window: { location, EventSource: Events, addEventListener: (key, fn) => (windows[key] = fn) },
  URL: LocalURL,
  Blob,
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
  fetch: async () => {
    fetches++;
    return { ok: true, json: async () => fixture };
  },
  setInterval: () => 1,
  setTimeout: (fn, ms) => {
    if (ms === 1000) timers.push(fn);
    return 1;
  },
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
function filter(id, value, event = 'change') {
  ids[id].value = value;
  ids[id].dispatch(event);
}
function emit(events, extra = {}) {
  Events.instances[0].emit({ ...fixture, events, ...extra });
}
async function exported() {
  ids.journalExport.click();
  const entry = downloads.at(-1);
  return { entry, data: JSON.parse(await blobs.get(entry.href).text()) };
}
(async () => {
  vm.runInNewContext(script, sandbox, { filename: 'app.js' });
  await new Promise(setImmediate);
  check(
    ids.journalRows.textContent.indexOf(a.message) < ids.journalRows.textContent.indexOf(b.message),
    'journal is chronological despite reverse-ordered source',
  );
  check(
    ids.journalSnapshot.textContent.includes('80') &&
      ids.journalSnapshot.textContent.includes('pas un historique exhaustif'),
    'bounded snapshot scope is explicit',
  );
  check(!ids.journalExport.disabled, 'nonempty journal can be exported on demand');
  ids.journalRows.scrollTop = 127;
  const originalFirst = ids.journalRows.children[0];
  ids.journalPause.click();
  check(ids.journalPause.attributes['aria-pressed'] === 'true', 'freeze exposes its pressed state');
  check(
    ids.journalSnapshot.textContent.includes('collecte et indicateurs non suspendus'),
    'freeze does not imply simulation or data collection pause',
  );
  check(!ids.journalResume.hidden, 'resume action appears while frozen');
  const replacements = ids.journalRows.replacements;
  emit([
    { ...b, id: 'regenerated-b' },
    { ...a, id: 'regenerated-a' },
  ]);
  check(
    ids.journalPending.textContent.startsWith('0 nouvel événement'),
    'producer ID churn is not counted as a new observation',
  );
  check(
    ids.journalRows.replacements === replacements && ids.journalRows.children[0] === originalFirst,
    'frozen rows retain their identity and selection',
  );
  emit([c, { ...b, id: 'reindexed-b' }, { ...a, id: 'reindexed-a' }], {
    capture: { status: 'capturing', captured: 3, expected: 9 },
    generatedAt: stamp(40),
  });
  check(
    ids.journalPending.textContent.startsWith('1 nouvel événement'),
    'one new stable observation is counted',
  );
  check(!ids.journalRows.textContent.includes(c.message), 'new events do not replace frozen rows');
  check(
    !ids.eventSource.options.some((option) => option.value === 'new-source'),
    'frozen source choices reflect frozen content',
  );
  check(
    ids.captureKpi.textContent === '3/ 9',
    'capture indicators continue updating during the journal freeze',
  );
  check(
    ids.journalRows.scrollTop === 127 && ids.journalRows.replacements === replacements,
    'incoming data preserves frozen scroll and DOM',
  );
  check(
    !Events.instances[0].closed && fetches === 1,
    'freeze neither closes SSE nor launches a collection replacement',
  );
  ids.autoScroll.checked = true;
  ids.autoScroll.dispatch('change');
  check(
    ids.journalRows.scrollTop === 127,
    'enabling following while frozen cannot move the frozen view',
  );
  ids.autoScroll.checked = false;
  filter('eventLevel', 'error');
  check(
    ids.eventCount.textContent === '1 événement' && ids.journalRows.textContent.includes(b.message),
    'level filtering applies to frozen events',
  );
  filter('eventSearch', 'CONTRÔLÉE', 'input');
  check(
    ids.eventCount.textContent === '1 événement',
    'case-insensitive search remains usable while frozen',
  );
  const frozenExport = await exported();
  check(
    frozenExport.data.provenance.displayFrozen === true && frozenExport.data.events.length === 1,
    'export contains only filtered frozen rows',
  );
  check(
    frozenExport.data.provenance.snapshotGeneratedAt === fixture.generatedAt,
    'frozen export retains original snapshot provenance',
  );
  check(
    frozenExport.data.events[0].message === b.message &&
      !frozenExport.data.events.some((e) => e.message === c.message),
    'unseen live messages are not exported as frozen content',
  );
  const many = Array.from({ length: 81 }, (_, i) => ({
    id: 'm' + i,
    at: stamp(50 + i),
    source: 'many',
    level: i === 80 ? 'error' : 'info',
    message: i === 80 ? '<script>alert(1)</script>' : 'Message ' + i,
    historical: false,
    secret: 'DO_NOT_EXPORT',
  }));
  emit(many, { generatedAt: stamp(140) });
  check(
    ids.journalPending.textContent.startsWith('80 nouveaux événements'),
    'pending observations are bounded by the latest 80-event window',
  );
  emit(
    many.map((e, i) => ({ ...e, id: 'changed-' + i })),
    { generatedAt: stamp(141) },
  );
  check(
    ids.journalPending.textContent.startsWith('80 nouveaux événements'),
    'ID reindexing does not accumulate fictitious pending observations',
  );
  filter('eventLevel', 'all');
  filter('eventSearch', '', 'input');
  ids.journalResume.click();
  check(
    ids.journalRows.scrollTop === ids.journalRows.scrollHeight,
    'explicit latest-events action moves to the latest visible rows',
  );
  check(
    ids.journalPause.attributes['aria-pressed'] === 'false' && ids.journalResume.hidden,
    'resume resets pause state',
  );
  check(ids.eventCount.textContent === '80 événements', 'resume reads the latest bounded snapshot');
  check(
    ids.journalRows.textContent.includes('Message 79') &&
      !ids.journalRows.textContent.includes(b.message),
    'resume cannot reintroduce obsolete frozen rows',
  );
  check(ids.journalPending.textContent === '', 'resume clears the pending indicator');
  check(
    ids.eventSource.options.some((option) => option.value === 'many'),
    'source choices resume with the current received window',
  );
  filter('eventLevel', 'error');
  filter('eventSearch', '<script>', 'input');
  check(
    ids.eventCount.textContent === '1 événement' &&
      ids.journalRows.textContent.includes('<script>'),
    'message markup is displayed as text',
  );
  const liveExport = await exported();
  check(
    liveExport.data.schema === 'lotusim-journal-export-1',
    'export schema identifies journal observations',
  );
  check(
    liveExport.data.events.length === 1 &&
      liveExport.data.events[0].message === '<script>alert(1)</script>',
    'export follows current filters exactly',
  );
  check(
    liveExport.data.filters.level === 'error' && liveExport.data.filters.query === '<script>',
    'export records active filters',
  );
  check(
    liveExport.data.provenance.maximumSnapshotEvents === 80 &&
      liveExport.data.provenance.exhaustiveHistory === false,
    'export does not claim a complete archive',
  );
  check(
    liveExport.data.displayTimeZone === 'Europe/Paris' &&
      typeof liveExport.data.exportedAtParis === 'string',
    'export carries Paris display time and UTC machine time',
  );
  check(
    /^journal_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_Paris\.json$/.test(liveExport.entry.name),
    'filename has an explicit Paris date',
  );
  check(
    !JSON.stringify(liveExport.data).includes('DO_NOT_EXPORT') &&
      !('capture' in liveExport.data) &&
      !('preview' in liveExport.data),
    'export whitelists event fields without full state, images or private extras',
  );
  check(
    liveExport.data.provenance.displayFrozen === false &&
      liveExport.data.provenance.snapshotGeneratedAt === stamp(141),
    'live export identifies its own observed snapshot',
  );
  filter('eventSearch', 'not-found', 'input');
  const beforeDownloads = downloads.length;
  ids.journalExport.click();
  check(
    ids.journalExport.disabled && downloads.length === beforeDownloads,
    'empty filtered view cannot produce a misleading export',
  );
  filter('eventSearch', '', 'input');
  filter('eventLevel', 'all');
  emit([b, a]);
  ids.autoScroll.checked = true;
  ids.journalRows.scrollTop = 700;
  emit([c, b, a]);
  check(
    ids.journalRows.scrollTop === 1000,
    'following detects a new newest event even when the oldest source item is unchanged',
  );
  ids.autoScroll.checked = false;
  ids.journalRows.scrollTop = 118;
  const rowsBeforeReindexing = ids.journalRows.replacements;
  emit([{ ...c, id: 'changed-c' }, b, a]);
  check(ids.journalRows.scrollTop === 118, 'non-following live view preserves its scroll position');
  check(
    ids.journalRows.replacements === rowsBeforeReindexing,
    'producer ID reindexing does not rebuild visually identical live rows',
  );
  const rowsBeforeIdentical = ids.journalRows.replacements;
  emit([{ ...c, id: 'changed-c' }, b, a]);
  check(
    ids.journalRows.replacements === rowsBeforeIdentical,
    'unchanged snapshots do not rebuild journal rows',
  );
  timers.forEach((fn) => fn());
  check(
    LocalURL.revoked.length === 2,
    'download object URLs are released after user-initiated exports',
  );
  check(
    !/method\s*:\s*['"](?:POST|PUT|PATCH|DELETE)/.test(script),
    'journal controls contain no server mutation',
  );
  console.log(checks + ' journal freeze, filtering and local export checks passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
