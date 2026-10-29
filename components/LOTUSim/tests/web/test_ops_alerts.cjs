/* Alert classification and a minimal DOM; all values are explicit fixtures. */
'use strict';
const { uiFile, coreRoot } = require('./support/paths.cjs');
const assert = require('node:assert/strict'),
  path = require('node:path');
const ui = process.argv[2] || path.join(__dirname, '../../tools/ops_dashboard_ui');
const { collect, deduplicate, createStore, mount } = require(uiFile(ui, 'alerts.js'));
let checks = 0;
function check(value, message) {
  assert.ok(value, message);
  checks++;
}
const now = '2026-10-28T14:00:00Z';
const warnings = Array.from({ length: 7 }, (_, i) => 'Avertissement ' + i);
const base = {
  generatedAt: now,
  health: { warnings: [...warnings, warnings[0], '', null] },
  services: [],
};
check(
  deduplicate(collect(base)).length === 7,
  'all seven warnings are preserved without duplicates',
);
check(
  collect({}).length === 0 && collect(null).length === 0,
  'missing state never invents a problem',
);
const state = {
  ...base,
  health: { warnings: [], error: 'Collecte inaccessible' },
  services: [
    { id: 'ros', label: 'ROS TCP', state: 'error', detail: 'Erreur de liaison' },
    { id: 'renderer', label: 'Unity', state: 'paused', detail: 'Pause volontaire' },
    { id: 'optional', state: 'stopped', optional: true },
    { id: 'unknown', state: 'unknown' },
    { id: 'stale', label: 'Signal', state: 'stale', detail: 'Signal ancien' },
  ],
  capture: { state: 'failed', historical: true, updatedAt: now, error: 'Ancien échec' },
  vision: { state: 'error', updatedAt: '2026-10-28T13:59:59Z', error: 'Analyse refusée' },
  preparation: {
    state: 'failed',
    updatedAt: '2020-01-01T00:00:00Z',
    error: 'Ancienne préparation',
  },
};
const notices = collect(state);
check(notices.length === 4, 'collector, actual service states and recent unarchived job only');
check(
  !notices.some((n) => /Ancien|volontaire/.test(n.message)),
  'historical failures, voluntary pauses and optional stopped services are not incidents',
);
check(
  notices.filter((n) => n.level === 'error').length === 3,
  'severity is explicit, not inferred from a CSS colour',
);
check(
  !collect({ ...state, vision: { state: 'error', fresh: false, updatedAt: now } }).some(
    (n) => n.source === 'Analyse RGB',
  ),
  'stale job cannot be presented as a new error',
);
check(
  collect({
    ...state,
    vision: { state: 'ready', status: 'failed', historical: false, updatedAt: now },
  }).some((n) => n.source === 'Analyse RGB'),
  'fresh explicit job failure wins over a normalized ready state',
);
check(
  !collect({ ...state, vision: { state: 'stale', status: 'failed', updatedAt: now } }).some(
    (n) => n.source === 'Analyse RGB',
  ),
  'stale normalized state cannot create a new job incident',
);
check(
  !collect({ ...state, vision: { state: 'error', updatedAt: '2026-10-28T15:00:00Z' } }).some(
    (n) => n.source === 'Analyse RGB',
  ),
  'future timestamps cannot establish recent activity',
);
const store = createStore();
store.update(base);
store.publish('form', {
  key: 'a',
  source: 'Trafic',
  level: 'error',
  message: 'Refus',
  route: 'traffic',
});
check(
  store.items().length === 8 && store.items()[0].level === 'error',
  'errors sort first and coexist with snapshot diagnostics',
);
store.publish('form', { source: 'Trafic', level: 'error', message: 'Refus', route: 'traffic' });
check(store.items().length === 8, 'same scoped action replaces itself, not duplicated on a poll');
store.publish('form', null);
check(store.items().length === 7, 'successful or cleared action removes its old local alert');
store.update({ health: { warnings: [] } });
check(
  store.items().length === 0,
  'resolved snapshot points disappear rather than remaining falsely active',
);
store.transport({
  source: 'Liaison',
  level: 'error',
  message: 'Collecteur perdu',
  route: 'overview',
});
check(store.items().length === 1, 'transport error is independent of empty data');
store.transport(null);
check(store.items().length === 0, 'restored transport clears only its own point');

class Element {
  constructor(tag = 'div', id = '') {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.attributes = {};
    this._text = '';
    this.className = '';
    this.open = false;
    this.hidden = false;
    this.value = '';
    this.scrollTop = 0;
    this.replacements = 0;
    this.classList = {
      toggle: (key, on) => {
        const set = new Set(this.className.split(' ').filter(Boolean));
        on ? set.add(key) : set.delete(key);
        this.className = [...set].join(' ');
      },
    };
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((x) => x.textContent || '').join('');
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
    this.attributes[key] = value;
  }
  addEventListener(key, fn) {
    (this.listeners[key] ||= []).push(fn);
  }
  dispatch(key, event = {}) {
    for (const fn of this.listeners[key] || []) fn({ target: this, ...event });
  }
  querySelectorAll() {
    return this.children.flatMap((x) => [
      ...(x.tagName === 'DETAILS' && x.dataset.source ? [x] : []),
      ...x.querySelectorAll(),
    ]);
  }
  contains(target) {
    return this === target || this.children.some((x) => x.contains(target));
  }
  focus() {
    this.focused = true;
  }
}
const names = [
  'alertCenter',
  'alertCount',
  'alertToggle',
  'alertStatus',
  'alertFreshness',
  'alertFilter',
  'alertItems',
  'alertClose',
  'alertJournal',
];
const ids = Object.fromEntries(names.map((id) => [id, new Element('div', id)]));
ids.alertFilter.value = 'all';
const doc = {
  getElementById: (id) => ids[id],
  createElement: (tag) => new Element(tag),
  listeners: {},
  addEventListener(key, fn) {
    this.listeners[key] = fn;
  },
};
const api = mount({ document: doc });
check(
  ids.alertStatus.textContent === 'Aucun point signalé' &&
    ids.alertItems.textContent.includes('Aucun état reçu'),
  'empty centre does not claim chain readiness',
);
api.update(base);
check(
  ids.alertCount.textContent === '7' &&
    warnings.every((w) => ids.alertItems.textContent.includes(w)),
  'browser centre renders every global warning',
);
check(
  ids.alertItems.children.length === 1 &&
    ids.alertItems.children[0].dataset.source === 'Diagnostic de la chaîne',
  'points grouped by their actual source',
);
ids.alertItems.children[0].open = false;
ids.alertItems.scrollTop = 37;
const before = ids.alertItems.replacements;
api.update({ ...base, generatedAt: '2026-10-28T14:00:02Z' });
check(
  ids.alertItems.replacements === before &&
    !ids.alertItems.children[0].open &&
    ids.alertItems.scrollTop === 37,
  'identical observations preserve disclosure state and scroll',
);
api.update({ ...base, health: { warnings: [...warnings, 'Encore un point'] } });
check(
  !ids.alertItems.children[0].open && ids.alertItems.scrollTop === 37,
  'changed list preserves user-closed source group',
);
ids.alertFilter.value = 'error';
ids.alertFilter.dispatch('change');
check(
  ids.alertItems.textContent.includes('Aucun point de ce niveau'),
  'level filter is functional',
);
const target = new Element('div', 'trafficNotice'),
  message = '<img src=x onerror=alert(1)> Refus de fixture';
api.notify(target, message, 'error', { source: 'Trafic', route: 'traffic', label: 'Génération' });
check(
  !target.hidden && target.children[0].tagName === 'DETAILS' && !target.children[0].open,
  'long action feedback is a native disclosure, not a tall permanent banner',
);
check(
  target.textContent.includes('Erreur · Génération') && target.textContent.includes(message),
  'visible summary includes explicit severity and preserves complete text',
);
check(
  target.children[0].children[1].tagName === 'P' &&
    target.children[0].children[1].textContent === message,
  'untrusted message remains text, never markup',
);
check(
  ids.alertCount.textContent === '9' && ids.alertItems.textContent.includes(message),
  'scoped action also appears in the central error filter',
);
const replacements = target.replacements;
target.children[0].open = true;
api.notify(target, message, 'error', { source: 'Trafic', route: 'traffic', label: 'Génération' });
check(
  target.replacements === replacements && target.children[0].open,
  'unchanged action feedback does not reset user reading',
);
api.notify(target, 'Enregistré', 'success', { source: 'Trafic', route: 'traffic' });
check(
  target.textContent === 'Enregistré' && ids.alertCount.textContent === '8',
  'success replaces inline error and clears central scoped alert',
);
api.notify(target, '', '', { source: 'Trafic', route: 'traffic' });
check(target.hidden, 'empty feedback hides cleanly');
ids.alertCenter.open = true;
let prevented = false;
doc.listeners.keydown({
  key: 'Escape',
  preventDefault() {
    prevented = true;
  },
});
check(
  !ids.alertCenter.open && ids.alertToggle.focused && prevented,
  'Escape closes centre and returns keyboard focus',
);
ids.alertCenter.open = true;
doc.listeners.click({ target: new Element('button') });
check(!ids.alertCenter.open, 'outside click closes only the centre');
ids.alertCenter.open = true;
ids.alertJournal.dispatch('click');
check(!ids.alertCenter.open, 'journal link closes the centre');
api.setTransport({ level: 'error', message: 'Connexion perdue' });
check(
  ids.alertFreshness.textContent.includes('non actualisée') && ids.alertCount.textContent === '9',
  'disconnected centre identifies that retained states are not current',
);
api.setTransport(null);
api.update({ generatedAt: 'bad', health: { warnings: [] } });
check(
  ids.alertFreshness.textContent.includes('non mesurée'),
  'invalid clock data does not crash the centre',
);
console.log(checks + ' alert classification, disclosure and keyboard checks passed');
