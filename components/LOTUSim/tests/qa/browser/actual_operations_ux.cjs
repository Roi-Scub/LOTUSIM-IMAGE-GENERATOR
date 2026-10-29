/* Installed dashboard QA: real GETs/SSE only; every mutation is blocked. */
'use strict';
const { uiFile, coreRoot } = require('../../web/support/paths.cjs');
const fs = require('node:fs'),
  path = require('node:path'),
  cp = require('node:child_process'),
  assert = require('node:assert/strict');
const origin = 'http://127.0.0.1:8766',
  root = coreRoot,
  output = path.join(root, 'artifacts', 'qa', 'actual-operations-ux');
fs.mkdirSync(output, { recursive: true });
const profile = fs.mkdtempSync('/private/tmp/lotusim-actual-operations-ux-'),
  pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const pending = new Map(),
  events = [],
  blockedWrites = [],
  interceptionErrors = [],
  screenshots = [];
let browser,
  connection,
  sequence = 0,
  checks = 0;
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
async function click(id) {
  await evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);
}
async function set(id, value, event = 'change') {
  await evaluate(
    `(()=>{const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event(${JSON.stringify(event)},{bubbles:true}));})()`,
  );
}
async function shot(name) {
  const result = await send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
  });
  const file = path.join(output, name);
  fs.writeFileSync(file, Buffer.from(result.data, 'base64'));
  screenshots.push(file);
}
async function get(route) {
  const response = await fetch(origin + route);
  assert.ok(response.ok, 'GET ' + route);
  return response.json();
}
async function intercepted(item) {
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
  const plansBefore = await get('/api/traffic/plans'),
    enginesBefore = await get('/api/engines');
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
  connection = new WebSocket(targets.find((target) => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    connection.addEventListener('open', resolve, { once: true });
    connection.addEventListener('error', reject, { once: true });
  });
  connection.addEventListener('message', (message) => {
    const item = JSON.parse(message.data);
    if (item.id && pending.has(item.id)) {
      const task = pending.get(item.id);
      pending.delete(item.id);
      item.error ? task.reject(Error(JSON.stringify(item.error))) : task.resolve(item.result);
    } else {
      events.push(item);
      if (item.method === 'Fetch.requestPaused')
        intercepted(item).catch((error) => interceptionErrors.push(error.stack));
    }
  });
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1660,
    height: 1200,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send('Page.navigate', { url: origin + '/#journal' });
  await waitFor(
    "window.LotusimAlerts&&document.getElementById('journalPause')&&!document.getElementById('journalPause').disabled&&document.getElementById('connectionText').textContent==='Flux local connecté'",
  );
  check(
    await evaluate(
      "document.querySelector('script[src=\"/alerts.js\"]')&&document.querySelector('link[href=\"/operations-ux.css\"]')&&document.getElementById('journalExport')",
    ),
    'installed scripts, styles and journal controls are present',
  );
  check(
    await evaluate(
      "document.getElementById('journalSnapshot').textContent.includes('80')&&document.getElementById('journalSnapshot').textContent.includes('pas un historique exhaustif')",
    ),
    'real journal discloses its bounded non-exhaustive scope',
  );
  const observedRows = await evaluate(
    "document.querySelectorAll('#journalRows .journal-row').length",
  );
  check(observedRows <= 80, 'real displayed journal is bounded to eighty observations');
  await click('alertToggle');
  check(
    await evaluate("document.getElementById('alertCenter').open"),
    'installed alert center opens',
  );
  check(
    await evaluate(
      "document.getElementById('alertFreshness').textContent.includes('Dernier état reçu')||document.getElementById('alertFreshness').textContent.includes('non actualisée')",
    ),
    'alert center labels real state freshness rather than inventing readiness',
  );
  await shot('actual-alerts-desktop.png');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape' });
  check(
    await evaluate(
      "!document.getElementById('alertCenter').open&&document.activeElement.id==='alertToggle'",
    ),
    'Escape restores focus to the real alert control',
  );
  const syncBefore = await evaluate("document.getElementById('lastSync').textContent");
  await evaluate(
    "window.__realFrozenText=document.getElementById('journalRows').textContent;window.__realFrozenFirst=document.getElementById('journalRows').firstElementChild;document.getElementById('journalRows').scrollTop=30;window.__realFrozenScroll=document.getElementById('journalRows').scrollTop",
  );
  await click('journalPause');
  check(
    await evaluate(
      "document.getElementById('journalPause').getAttribute('aria-pressed')==='true'&&!document.getElementById('journalResume').hidden",
    ),
    'real journal enters display-only freeze',
  );
  await waitFor(
    `document.getElementById('lastSync').textContent!==${JSON.stringify(syncBefore)}`,
    12000,
  );
  check(
    await evaluate(
      "document.getElementById('journalRows').textContent===window.__realFrozenText&&document.getElementById('journalRows').firstElementChild===window.__realFrozenFirst&&document.getElementById('journalRows').scrollTop===window.__realFrozenScroll",
    ),
    'a real incoming snapshot keeps frozen rows and scroll unchanged',
  );
  check(
    await evaluate(
      "document.getElementById('connectionText').textContent==='Flux local connecté'&&document.getElementById('journalSnapshot').textContent.includes('collecte et indicateurs non suspendus')",
    ),
    'the real SSE stream and telemetry continue during the display freeze',
  );
  await shot('actual-journal-desktop.png');
  await click('journalResume');
  check(
    await evaluate(
      "document.getElementById('journalPause').getAttribute('aria-pressed')==='false'&&document.getElementById('journalResume').hidden",
    ),
    'resume returns to the latest real snapshot',
  );
  await evaluate("document.querySelector('[data-route=settings]').click()");
  await waitFor("!document.getElementById('settingsEditor').hidden");
  check(
    await evaluate(
      "!!document.querySelector('#settingsEngineNote details.context-details')&&!document.querySelector('#settingsEngineNote details.context-details').open",
    ),
    'installed engine details start collapsed',
  );
  check(
    await evaluate(
      "document.querySelectorAll('#settingsEngineNote .settings-engine-states>span').length===3",
    ),
    'compact real engine status badges remain visible',
  );
  await evaluate("document.querySelector('[data-route=traffic]').click()");
  await waitFor(
    `!document.getElementById('trafficWorkspace').hidden&&document.getElementById('trafficPlanChoice').options.length===${plansBefore.plans.length + 1}`,
  );
  const ready = plansBefore.plans.find((plan) => plan.ready);
  if (ready) {
    await set('trafficPlanChoice', ready.id);
    await waitFor(
      `document.getElementById('trafficPlanChoice').value==='${ready.id}'&&!document.getElementById('trafficPlanChoice').disabled`,
    );
    check(
      await evaluate(
        "!document.getElementById('trafficAuditDetails').hidden&&!document.getElementById('trafficAuditDetails').open",
      ),
      'real stored limited audit is available as a collapsed disclosure',
    );
  }
  check(
    await evaluate(
      "getComputedStyle(document.getElementById('trafficNotice')).backgroundColor==='rgb(16, 38, 51)'",
    ),
    'real informational traffic message has a neutral style',
  );
  await evaluate("document.getElementById('trafficSource').scrollIntoView({block:'center'})");
  await shot('actual-traffic-desktop.png');
  await evaluate("document.querySelector('[data-route=journal]').click();window.scrollTo(0,0)");
  await send('Emulation.setDeviceMetricsOverride', {
    width: 430,
    height: 1050,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await click('alertToggle');
  await waitFor(
    "document.querySelector('.alerts-panel').getBoundingClientRect().top>=document.getElementById('alertToggle').getBoundingClientRect().bottom",
  );
  check(
    await evaluate('document.documentElement.scrollWidth<=innerWidth'),
    'actual mobile dashboard has no horizontal overflow',
  );
  check(
    await evaluate(
      "(()=>{const panel=document.querySelector('.alerts-panel').getBoundingClientRect(),toggle=document.getElementById('alertToggle').getBoundingClientRect();return panel.left>=0&&panel.right<=innerWidth&&panel.top>=toggle.bottom&&panel.bottom<=innerHeight;})()",
    ),
    'actual mobile alert panel is aligned below its control and inside the viewport',
  );
  await shot('actual-alerts-mobile.png');
  await click('alertClose');
  await shot('actual-journal-mobile.png');
  const plansAfter = await get('/api/traffic/plans'),
    enginesAfter = await get('/api/engines');
  check(
    JSON.stringify(plansAfter.plans.map((plan) => [plan.id, plan.planSha256])) ===
      JSON.stringify(plansBefore.plans.map((plan) => [plan.id, plan.planSha256])),
    'all production library revision hashes remain unchanged',
  );
  check(
    enginesAfter.selectedEngine.id === enginesBefore.selectedEngine.id,
    'production engine profile remains unchanged',
  );
  check(blockedWrites.length === 0, 'the real tested journey attempts no server mutation');
  const errors = events
    .filter((event) => event.method === 'Runtime.exceptionThrown')
    .map(
      (event) =>
        event.params.exceptionDetails?.exception?.description ||
        event.params.exceptionDetails?.text,
    );
  check(
    errors.length === 0 && interceptionErrors.length === 0,
    'no real browser JavaScript or interception errors',
  );
  const result = {
    passed: true,
    checks,
    evidence:
      'Installed resources and unmodified real GET/SSE state. No synthetic events, no POST, no Unity/ROS/simulation operation, no image generation.',
    observedRows,
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
