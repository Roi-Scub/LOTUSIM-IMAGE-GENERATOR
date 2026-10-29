/* Actual installed dashboard, unmocked GETs; every browser mutation blocked. */
'use strict';
const { uiFile, coreRoot } = require('../../web/support/paths.cjs');
const fs = require('node:fs'),
  path = require('node:path'),
  cp = require('node:child_process'),
  assert = require('node:assert/strict');
const origin = 'http://127.0.0.1:8766',
  output = path.resolve(coreRoot, 'artifacts', 'qa', 'actual-engine-traffic-ui');
fs.mkdirSync(output, { recursive: true });
const profile = fs.mkdtempSync('/private/tmp/lotusim-actual-engine-traffic-ui-'),
  pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let browser,
  connection,
  sequence = 0,
  checks = 0,
  registry,
  plan;
const pending = new Map(),
  events = [],
  blockedWrites = [],
  interceptionErrors = [],
  screenshots = [];
const check = (value, message) => {
  assert.ok(value, message);
  checks++;
};
async function send(method, params = {}) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    connection.send(JSON.stringify({ id, method, params }));
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        reject(Error('CDP timeout: ' + method));
      }
    }, 15000).unref();
  });
}
async function evaluate(expression) {
  const result = await send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails)
    throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
}
async function waitFor(expression, ms = 20000) {
  const stop = Date.now() + ms;
  while (Date.now() < stop) {
    if (await evaluate(expression)) return;
    await pause(100);
  }
  throw Error('Timed out: ' + expression);
}
async function set(id, value, event = 'input') {
  await evaluate(
    `(()=>{const node=document.getElementById(${JSON.stringify(id)});node.value=${JSON.stringify(String(value))};node.dispatchEvent(new Event(${JSON.stringify(event)},{bubbles:true}));})()`,
  );
}
async function shot(name) {
  const data = await send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
  });
  const file = path.join(output, name);
  fs.writeFileSync(file, Buffer.from(data.data, 'base64'));
  screenshots.push(file);
}
async function paused(item) {
  const request = item.params.request,
    requestId = item.params.requestId,
    url = new URL(request.url);
  if (!['GET', 'HEAD'].includes(request.method)) {
    blockedWrites.push({ method: request.method, path: url.pathname });
    return send('Fetch.failRequest', { requestId, errorReason: 'BlockedByClient' });
  }
  if (url.origin !== origin)
    return send('Fetch.failRequest', { requestId, errorReason: 'BlockedByClient' });
  return send('Fetch.continueRequest', { requestId });
}
(async () => {
  registry = await (await fetch(origin + '/api/engines')).json();
  plan = await (await fetch(origin + '/api/traffic/plan')).json();
  check(
    registry.schema === 'lotusim-engine-catalog-1' && registry.selectedEngine?.id,
    'real registry exposes a persisted project profile',
  );
  check(
    ['unity', 'unreal', 'godot', 'blender', 'o3de'].every((id) =>
      registry.engines.some((engine) => engine.id === id),
    ),
    'real registry includes all five built-in descriptors',
  );
  check(
    plan.available === true && plan.actors.length === 32 && !!plan.observer,
    'real API exposes the existing 32 actors and observer',
  );
  browser = cp.spawn(
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    [
      '--headless=new',
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-background-networking',
      '--disable-sync',
      '--disable-extensions',
      '--remote-debugging-port=0',
      '--user-data-dir=' + profile,
      'about:blank',
    ],
    { stdio: 'ignore' },
  );
  const active = path.join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 100 && !fs.existsSync(active); i++) await pause(100);
  check(fs.existsSync(active), 'owned isolated Chrome starts');
  const port = Number(fs.readFileSync(active, 'utf8').split('\n')[0]),
    targets = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
  connection = new WebSocket(targets.find((value) => value.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    connection.addEventListener('open', resolve, { once: true });
    connection.addEventListener('error', reject, { once: true });
  });
  connection.addEventListener('message', (message) => {
    const item = JSON.parse(message.data);
    if (item.id && pending.has(item.id)) {
      const request = pending.get(item.id);
      pending.delete(item.id);
      item.error ? request.reject(Error(JSON.stringify(item.error))) : request.resolve(item.result);
    } else {
      events.push(item);
      if (item.method === 'Fetch.requestPaused')
        paused(item).catch((error) => interceptionErrors.push(error.stack));
    }
  });
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1660,
    height: 1250,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send('Page.navigate', { url: origin + '/#settings' });
  await waitFor(
    `!document.getElementById('settingsEditor').hidden&&document.getElementById('engineProfileCurrent').textContent===${JSON.stringify(registry.selectedEngine.label)}`,
  );
  check(
    await evaluate(
      "['unity','unreal','godot','blender','o3de','custom'].every(value=>[...document.getElementById('engineProfileChoice').options].some(option=>option.value===value))",
    ),
    'installed profile selector is populated by registry descriptors',
  );
  const initialCampaign = await evaluate("document.getElementById('settings-field-engine').value");
  await set('engineProfileChoice', 'godot', 'change');
  check(
    await evaluate(
      `document.getElementById('engineProfileCurrent').textContent===${JSON.stringify(registry.selectedEngine.label)}&&document.getElementById('settings-field-engine').value===${JSON.stringify(initialCampaign)}`,
    ),
    'changing an un-applied profile choice changes neither persisted profile nor campaign engine',
  );
  check(
    await evaluate("document.getElementById('engineProfileChoiceDetail').textContent.length>0"),
    'descriptor capabilities are available before any explicit profile save',
  );
  await shot('actual-engine-registry-settings.png');
  await evaluate("document.querySelector('[data-route=traffic]').click()");
  await waitFor(
    "!document.getElementById('trafficWorkspace').hidden&&document.querySelectorAll('.traffic-object').length===32",
  );
  check(
    await evaluate("document.querySelectorAll('#trafficMap polyline').length===33"),
    'installed map shows all trajectories and the observer',
  );
  check(
    await evaluate(
      "['sea','air','moored','observer'].every(domain=>{const item=document.querySelector('.traffic-legend-'+domain);return item&&getComputedStyle(item).backgroundColor!=='rgba(0, 0, 0, 0)'})",
    ),
    'all four legend colors are actually visible under the real dashboard CSP',
  );
  check(
    await evaluate(
      `document.getElementById('trafficSource').textContent.includes(${JSON.stringify(plan.source.relativePath)})`,
    ),
    'actual plan provenance is rendered independently of selected profile',
  );
  await set('trafficTime', 70);
  await evaluate("document.getElementById('trafficMap').scrollIntoView({block:'center'})");
  await shot('actual-cooperative-traffic-map.png');
  const actor = plan.actors.find(
    (actor) => actor.domain === 'sea' && actor.editable && actor.maxSpeedMps > 0,
  );
  await evaluate(
    `[...document.querySelectorAll('.traffic-object')].find(button=>button.dataset.actorId===${JSON.stringify(actor.id)}).click()`,
  );
  await set('trafficEast', actor.centerENU.eastM + 25);
  await evaluate("document.getElementById('trafficPreviewEdit').click()");
  check(
    await evaluate(
      "document.getElementById('trafficDraftCount').textContent==='1 objet modifié'&&document.getElementById('trafficDraftBadge').textContent==='Brouillon non enregistré'&&document.getElementById('trafficMapView').value==='selected'",
    ),
    'manual numeric edit remains an unsaved local preview with a useful selected-object map',
  );
  await evaluate("document.getElementById('trafficActorForm').scrollIntoView({block:'center'})");
  await shot('actual-unsaved-traffic-preview.png');
  await send('Emulation.setDeviceMetricsOverride', {
    width: 430,
    height: 1050,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await evaluate("document.getElementById('trafficMap').scrollIntoView({block:'start'})");
  check(
    await evaluate('document.documentElement.scrollWidth<=innerWidth'),
    'actual mobile traffic route has no horizontal overflow',
  );
  await shot('actual-traffic-mobile.png');
  const afterRegistry = await (await fetch(origin + '/api/engines')).json(),
    afterPlan = await (await fetch(origin + '/api/traffic/plan')).json();
  check(
    afterRegistry.selectedEngine.id === registry.selectedEngine.id &&
      afterPlan.baseSha256 === plan.baseSha256,
    'project profile and source plan hashes are unchanged after local browser edits',
  );
  check(blockedWrites.length === 0, 'read-only verification attempts no server mutation');
  const errors = events
    .filter((item) => item.method === 'Runtime.exceptionThrown')
    .map(
      (item) =>
        item.params.exceptionDetails?.exception?.description || item.params.exceptionDetails?.text,
    );
  check(
    errors.length === 0 && interceptionErrors.length === 0,
    'no JavaScript or request-safety errors',
  );
  const result = {
    passed: true,
    checks,
    evidence:
      'Actual installed UI and unmocked GETs; local browser choices only, never profile apply or draft save.',
    selectedProfile: registry.selectedEngine.id,
    actorCount: plan.actors.length,
    source: plan.source.relativePath,
    realServerMutations: 0,
    blockedWrites,
    errors,
    screenshots,
  };
  fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
})()
  .catch((error) => {
    const result = { passed: false, checks, error: error.stack, interceptionErrors, screenshots };
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
    console.error(JSON.stringify(result, null, 2));
    process.exitCode = 1;
  })
  .finally(async () => {
    if (connection) {
      try {
        await send('Browser.close');
      } catch (_) {}
      connection.close();
    }
    if (browser && !browser.killed) browser.kill('SIGTERM');
  });
