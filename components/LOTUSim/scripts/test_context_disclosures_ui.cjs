/* Disclosure and notice contracts only; no browser, server, engine or writes. */
'use strict';
const assert = require('node:assert/strict'),
  fs = require('node:fs'),
  path = require('node:path'),
  vm = require('node:vm');
const ui = path.resolve(process.argv[2] || path.join(__dirname, '../tools/ops_dashboard_ui'));
const { functionSource } = require('./source_contract_helpers.cjs');
const source = (name) => fs.readFileSync(path.join(ui, name + '.js'), 'utf8');
let checks = 0;
const check = (value, message) => {
  assert.ok(value, message);
  checks++;
};
class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.hidden = false;
    this.open = false;
    this.className = '';
    this._text = '';
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent || '').join('');
  }
  append(...values) {
    this.children.push(...values);
  }
  replaceChildren(...values) {
    this._text = '';
    this.children = values;
  }
  addEventListener(kind, callback) {
    this.listeners[kind] = callback;
  }
}
function between(text, first) {
  return functionSource(text, first);
}
const ids = {},
  get = (id) => ids[id] || (ids[id] = new Element());
const document = {
  createElement: (tag) => new Element(tag),
  createTextNode: (text) => {
    const n = new Element('text');
    n.textContent = text;
    return n;
  },
};
const make = (tag, text, kind) => {
  const n = new Element(tag);
  if (text != null) n.textContent = text;
  if (kind) n.className = kind;
  return n;
};
const settings = source('settings'),
  traffic = source('traffic'),
  assets = source('assets');
const calls = [],
  window = {
    LotusimAlerts: {
      notify(target, message, kind, meta) {
        calls.push({ target, message, kind, meta });
        target.textContent = message;
        target.hidden = !message;
      },
    },
  };
const context = {
  document,
  $: get,
  element: make,
  node: make,
  array: (v) => (Array.isArray(v) ? v : []),
  list: (v) => (Array.isArray(v) ? v : []),
  finite: (v) => typeof v === 'number' && Number.isFinite(v),
  fmt: String,
  window,
  expandedContext: new Map(),
  draft: { engine: 'unity' },
  engineFor: () => ({
    id: 'unity',
    label: 'Unity',
    preparationAvailable: true,
    nativeValidated: false,
    capabilities: {
      waves: true,
      annotations: true,
      livePoses: true,
      rgbCapture: true,
      scenePreparation: true,
      neutralExport: true,
    },
  }),
  engineLabel: () => 'Unity',
  canPrepare: () => true,
  contractOnly: () => false,
  selectedPlanId: 'source',
  plan: null,
  dirty: false,
  saving: false,
  revalidating: false,
  generating: false,
  auditDetailsKey: null,
  warningsDetailsKey: null,
  libraryBundle: () => null,
  uuid: () => false,
};
vm.createContext(context);
vm.runInContext(
  between(settings, 'contextDetails', 'function assetFor') +
    between(settings, 'renderEngineNote', 'function renderCapabilities') +
    between(settings, 'renderCapabilities', 'function profileNotice') +
    between(settings, 'renderValidation', 'function renderPrepared') +
    between(settings, 'renderEngineAgent', 'function validFields'),
  context,
);
context.renderEngineNote();
let details = get('settingsEngineNote').children.find((n) => n.tagName === 'DETAILS');
check(
  details && details.className === 'context-details' && !details.open,
  'long engine context starts folded',
);
check(
  details.children[0].tagName === 'SUMMARY' && details.children[0].textContent.includes('7 points'),
  'engine context summary announces its actual point budget',
);
check(
  get('settingsEngineNote').children[1].tagName === 'SPAN' &&
    get('settingsEngineNote').children[1].textContent.includes('Exécution native non validée'),
  'simple capability badges remain visible above disclosure',
);
details.open = true;
details.listeners.toggle();
context.renderEngineNote();
details = get('settingsEngineNote').children.find((n) => n.tagName === 'DETAILS');
check(details.open, 'explicit engine disclosure expansion survives redraw');
const profile = new Element();
context.renderCapabilities({ id: 'unreal', capabilities: {} }, profile);
check(
  profile.children[0].tagName === 'DETAILS' && profile.children[0].textContent.includes('6 points'),
  'profile capability grid has a separate bounded disclosure',
);
context.renderValidation({
  valid: false,
  errors: [{ path: 'blocks[0]', message: 'Budget invalide <img>' }],
  warnings: [{ path: 'sea', message: 'Houle non calibrée' }],
});
check(
  get('settingsValidation').children[1].tagName === 'UL' &&
    get('settingsValidation').children[1].textContent.includes('Budget invalide <img>'),
  'blocking field errors stay inline, as text',
);
check(
  get('settingsValidation').children[2].tagName === 'DETAILS' &&
    !get('settingsValidation').children[2].open &&
    get('settingsValidation').children[2].textContent.includes('1 point'),
  'nonblocking validation warnings are folded with a count',
);
const prepared = new Element();
context.renderEngineAgent({ limitations: ['Mer non calibrée', 'Pas de ROS'] }, prepared);
check(
  prepared.children[0].children.some(
    (n) => n.tagName === 'DETAILS' && n.textContent.includes('2 points'),
  ),
  'prepared adapter limits are also foldable',
);

for (const [text, name, next, target, route] of [
  [settings, 'profileNotice', 'function updateProfileChoice', 'engineProfileNotice', 'settings'],
  [settings, 'notice', 'function markDirty', 'settingsNotice', 'settings'],
  [traffic, 'notice', 'const uuid', 'trafficNotice', 'traffic'],
  [assets, 'notice', 'function glyph', 'assetLibraryNotice', 'assets'],
  [assets, 'integrationNotice', 'function uploadNotice', 'assetIntegrationNotice', 'assets'],
  [assets, 'uploadNotice', 'async function submitUpload', 'assetUploadNotice', 'assets'],
]) {
  vm.runInContext(between(text, name, next), context);
  context[name]('Refus explicite', 'error');
  let call = calls.at(-1);
  check(
    call.target === get(target) &&
      call.kind === 'error' &&
      call.meta.route === route &&
      !!call.meta.label,
    'notice forwards its exact target and contextual route: ' + target,
  );
  context[name]('', 'success');
  check(
    calls.at(-1).message === '' && calls.at(-1).kind === 'success',
    'success/empty notice clears the same alert source: ' + target,
  );
  const helper = window.LotusimAlerts;
  delete window.LotusimAlerts;
  context[name]('Fallback <script>', 'error');
  check(
    get(target).textContent === 'Fallback <script>' &&
      !get(target).hidden &&
      get(target).className.includes('error'),
    'legacy plain-text fallback works without global helper: ' + target,
  );
  window.LotusimAlerts = helper;
}

vm.runInContext(between(traffic, 'renderRecord', 'function actorFor'), context);
context.plan = {
  baseSha256: 'a',
  audit: { checks: [], limitations: ['Modèle borné'], errors: [] },
};
context.renderRecord();
check(
  !get('trafficAuditDetails').open && get('trafficAuditSummary').textContent.includes('1 point'),
  'nonblocking audit explanations are initially folded',
);
context.plan.audit.errors = ['Collision'];
context.renderRecord();
check(
  get('trafficAuditDetails').open && get('trafficAuditSummary').textContent.includes('à examiner'),
  'new audit errors auto-open their context',
);
get('trafficAuditDetails').open = false;
context.renderRecord();
check(
  !get('trafficAuditDetails').open,
  'the same unchanged audit never reopens after user collapse',
);
context.plan.audit.errors = ['Nouvelle collision'];
context.renderRecord();
check(get('trafficAuditDetails').open, 'a genuinely changed audit failure is shown automatically');
context.plan.audit = { checks: [] };
context.renderRecord();
check(
  get('trafficAuditDetails').hidden,
  'empty audit explanations do not leave a blank disclosure',
);
check(
  !settings.includes('innerHTML') &&
    !traffic.includes('innerHTML') &&
    !assets.includes('innerHTML'),
  'all contextual untrusted text remains text, not HTML',
);
console.log(checks + ' contextual disclosure and alert-bridge checks passed');
