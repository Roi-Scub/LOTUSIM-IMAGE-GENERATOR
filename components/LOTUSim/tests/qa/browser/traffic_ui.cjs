/* Actual existing plan rendered with staged UI; draft writes intercepted in memory. */
'use strict';
const { uiFile, coreRoot } = require('../../web/support/paths.cjs');
const fs = require('node:fs'),
  path = require('node:path'),
  cp = require('node:child_process'),
  assert = require('node:assert/strict');
const origin = 'http://127.0.0.1:8766',
  stage = coreRoot,
  output = path.join(stage, 'artifacts', 'qa', 'traffic-ui');
fs.mkdirSync(output, { recursive: true });
const uiRoot = fs.existsSync(path.join(stage, 'ui', 'index.html'))
  ? path.join(stage, 'ui')
  : path.join(stage, 'tools', 'ops_dashboard_ui');
const profile = fs.mkdtempSync('/private/tmp/lotusim-traffic-ui-'),
  pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let browser,
  connection,
  sequence = 0,
  checks = 0,
  plan;
const pending = new Map(),
  events = [],
  interceptedWrites = [],
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
async function click(id) {
  await evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);
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
  const fulfill = (body, type = 'application/json', status = 200) =>
    send('Fetch.fulfillRequest', {
      requestId,
      responseCode: status,
      responseHeaders: [{ name: 'Content-Type', value: type }],
      body: Buffer.from(typeof body === 'string' ? body : JSON.stringify(body)).toString('base64'),
    });
  if (!['GET', 'HEAD'].includes(request.method)) {
    let body = request.postData || '';
    if (!body && item.params.networkId)
      body = (await send('Network.getRequestPostData', { requestId: item.params.networkId }))
        .postData;
    interceptedWrites.push({
      method: request.method,
      path: url.pathname,
      body,
      headers: request.headers,
    });
    if (request.method === 'POST' && url.pathname === '/api/traffic/drafts')
      return fulfill({
        id: 'b269d2da-662d-415c-8ea2-29127a51ffad',
        draft: { requiresRevalidation: true },
        preview: { ...plan, draftPreview: true, requiresRevalidation: true },
        applied: false,
        downloadUrl: '/api/traffic/drafts/b269d2da-662d-415c-8ea2-29127a51ffad/draft.json',
      });
    return fulfill({ error: 'All other UI writes blocked.' }, 'application/json', 403);
  }
  if (url.origin !== origin)
    return send('Fetch.failRequest', { requestId, errorReason: 'BlockedByClient' });
  if (url.pathname === '/')
    return fulfill(fs.readFileSync(uiFile(uiRoot, 'index.html'), 'utf8'), 'text/html');
  if (
    [
      '/app.js',
      '/settings.js',
      '/assets.js',
      '/traffic.js',
      '/styles.css',
      '/settings.css',
      '/traffic.css',
    ].includes(url.pathname)
  )
    return fulfill(
      fs.readFileSync(uiFile(uiRoot, url.pathname.slice(1)), 'utf8'),
      url.pathname.endsWith('.js') ? 'text/javascript' : 'text/css',
    );
  if (url.pathname === '/api/traffic/plan') return fulfill(plan);
  return send('Fetch.continueRequest', { requestId });
}
(async () => {
  const code =
    'import json,sys;sys.path.insert(0,sys.argv[1]);from traffic_plan_editor import TrafficPlanStore;print(json.dumps(TrafficPlanStore(sys.argv[2],sys.argv[3]).get()))';
  const read = cp.spawnSync(
    '/opt/homebrew/bin/python3',
    [
      '-c',
      code,
      path.join(stage, 'tools'),
      '/Users/gabrielricardon/Desktop/Perso/export/runtime/LOTUSim',
      '/Users/gabrielricardon/Desktop/Perso/export/runtime/LOTUSim-Unity-modules',
    ],
    { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 },
  );
  if (read.status !== 0) throw Error(read.stderr);
  plan = JSON.parse(read.stdout);
  check(
    plan.available === true && plan.actors.length === 32 && !!plan.observer,
    'read-only source module finds the actual existing 32-actor cooperative plan and observer',
  );
  const sourceSnapshot = JSON.stringify(plan),
    actor = plan.actors.find(
      (actor) => actor.domain === 'sea' && actor.editable && actor.maxSpeedMps > 0,
    );
  check(!!actor, 'existing plan has an editable sea actor with known capacity');
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
  await send('Page.navigate', { url: origin + '/#traffic' });
  await waitFor(
    "!document.getElementById('trafficWorkspace').hidden&&document.querySelectorAll('.traffic-object').length===32",
  );
  check(
    await evaluate(
      "document.querySelector('[data-route=traffic]').classList.contains('active')&&document.getElementById('modeTag').textContent==='BROUILLON HORS LIGNE'",
    ),
    'traffic route is explicit and separated from live simulation',
  );
  check(
    await evaluate(
      "document.querySelectorAll('#trafficMap polyline').length===33&&document.getElementById('trafficSource').textContent.includes('Unity')",
    ),
    'all existing tracks, read-only observer and actual plan provenance render',
  );
  await set('trafficTime', 70);
  await evaluate("document.getElementById('trafficMap').scrollIntoView({block:'center'})");
  await shot('traffic-existing-plan-map.png');
  await click('trafficPlay');
  await pause(400);
  await click('trafficPlay');
  check(
    (await evaluate("Number(document.getElementById('trafficTime').value)>70")) &&
      interceptedWrites.length === 0,
    'timeline playback is browser-only and produces no request',
  );
  await evaluate(
    `[...document.querySelectorAll('.traffic-object')].find(button=>button.dataset.actorId===${JSON.stringify(actor.id)}).click()`,
  );
  const east = actor.centerENU.eastM + 50,
    heading = (actor.headingDeg + 10) % 360;
  await set('trafficEast', east);
  await set('trafficHeading', heading);
  await click('trafficPreviewEdit');
  check(
    await evaluate(
      "document.getElementById('trafficVersion').value==='working'&&document.getElementById('trafficDraftCount').textContent==='1 objet modifié'",
    ),
    'numeric editing first creates one local preview change',
  );
  check(
    interceptedWrites.length === 0 && JSON.stringify(plan) === sourceSnapshot,
    'editing leaves actual source plan unchanged and does not write',
  );
  await evaluate("document.getElementById('trafficActorForm').scrollIntoView({block:'center'})");
  await shot('traffic-local-route-edit.png');
  await click('trafficSave');
  await waitFor("!document.getElementById('trafficSaved').hidden");
  check(
    interceptedWrites.length === 1 && interceptedWrites[0].path === '/api/traffic/drafts',
    'only explicit immutable draft save attempted, intercepted in browser memory',
  );
  const payload = JSON.parse(interceptedWrites[0].body);
  check(
    payload.baseSha256 === plan.baseSha256 &&
      payload.changes[0].actorId === actor.id &&
      payload.changes[0].centerENU.eastM === east,
    'save pins original source and only requested actor parameters',
  );
  check(
    await evaluate(
      "document.getElementById('trafficSavedLabel').textContent.includes('révalidation nécessaire')&&document.getElementById('trafficDraftBadge').textContent.includes('non appliqué')",
    ),
    'saved draft never claims collision clearance or native application',
  );
  await evaluate("document.getElementById('trafficSaved').scrollIntoView({block:'center'})");
  await shot('traffic-immutable-export.png');
  await send('Emulation.setDeviceMetricsOverride', {
    width: 430,
    height: 1050,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await evaluate("document.getElementById('trafficMap').scrollIntoView({block:'start'})");
  check(
    await evaluate('document.documentElement.scrollWidth<=innerWidth'),
    'mobile traffic view has no horizontal overflow',
  );
  await shot('traffic-mobile.png');
  const errors = events
    .filter((item) => item.method === 'Runtime.exceptionThrown')
    .map(
      (item) =>
        item.params.exceptionDetails?.exception?.description || item.params.exceptionDetails?.text,
    );
  check(errors.length === 0 && interceptionErrors.length === 0, 'no JavaScript or fixture errors');
  const result = {
    passed: true,
    checks,
    evidence:
      'Actual existing plan read without modification; staged browser UI and in-memory draft response only. No production writes or native application.',
    actorCount: plan.actors.length,
    source: plan.source.relativePath,
    realServerMutations: 0,
    interceptedWrites: interceptedWrites.map((item) => ({ method: item.method, path: item.path })),
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
