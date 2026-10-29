/* Actual installed library UI, unmocked GETs; every browser mutation blocked. */
'use strict';
const { uiFile, coreRoot } = require('../../web/support/paths.cjs');
const fs = require('node:fs'),
  path = require('node:path'),
  cp = require('node:child_process'),
  assert = require('node:assert/strict');
const origin = 'http://127.0.0.1:8766',
  output = path.resolve(coreRoot, 'artifacts', 'qa', 'actual-traffic-library-ui');
fs.mkdirSync(output, { recursive: true });
const profile = fs.mkdtempSync('/private/tmp/lotusim-actual-traffic-library-ui-'),
  pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let browser,
  connection,
  sequence = 0,
  checks = 0,
  library,
  record,
  plan,
  source,
  registry;
const pending = new Map(),
  events = [],
  blockedWrites = [],
  interceptionErrors = [],
  screenshots = [];
const check = (value, message) => {
  assert.ok(value, message);
  checks++;
};
async function get(route) {
  const response = await fetch(origin + route);
  assert.ok(response.ok, 'GET ' + route + ' returned ' + response.status);
  return response.json();
}
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
  const result = await send('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: false,
    }),
    file = path.join(output, name);
  fs.writeFileSync(file, Buffer.from(result.data, 'base64'));
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
  library = await get('/api/traffic/plans');
  source = await get('/api/traffic/plan');
  registry = await get('/api/engines');
  check(
    library.schema === 'lotusim-traffic-library-1' && Array.isArray(library.plans),
    'real SQLite library lists recorded plans',
  );
  record = library.plans.find((item) => item.ready === true && item.actorCount === 32);
  check(!!record, 'a real bounded-audit-approved 32-actor plan exists before this read-only QA');
  plan = await get('/api/traffic/plan?planId=' + record.id);
  check(
    plan.planId === record.id &&
      plan.actors.length === 32 &&
      plan.audit?.fullColregCompliance === false,
    'selected stored plan exposes its real trajectories and limited audit',
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
  connection = new WebSocket(targets.find((target) => target.type === 'page').webSocketDebuggerUrl);
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
    height: 1350,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send('Page.navigate', { url: origin + '/#traffic' });
  await waitFor(
    `!document.getElementById('trafficWorkspace').hidden&&document.getElementById('trafficPlanChoice').options.length===${library.plans.length + 1}`,
  );
  check(
    await evaluate("document.getElementById('trafficPlanChoice').value==='source'"),
    'historical source is explicit and reading the page does not activate a database plan',
  );
  await set('trafficPlanChoice', record.id, 'change');
  await waitFor(
    `document.getElementById('trafficPlanChoice').value==='${record.id}'&&!document.getElementById('trafficPlanChoice').disabled&&document.getElementById('trafficAuditBadge').textContent==='Contrôles limités satisfaits'`,
  );
  const pairCount = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(
      plan.audit.pairChecks,
    ),
    encounters = (plan.audit.limitedColreg?.checks || []).length,
    excluded = (plan.audit.limitedColreg?.excludedPairs || []).length;
  check(
    await evaluate(
      `document.getElementById('trafficAuditReasons').textContent.includes(${JSON.stringify(pairCount + ' séparations contrôlées')})&&document.getElementById('trafficAuditReasons').textContent.includes(${JSON.stringify(encounters + ' rencontres COLREG contrôlées')})&&document.getElementById('trafficAuditReasons').textContent.includes(${JSON.stringify(excluded + ' paires hors périmètre COLREG')})`,
    ),
    'real audit exposes separation, limited encounter and excluded-pair counts separately',
  );
  const auditLimits = new Set(
      (plan.audit.limitations || []).filter((value) => typeof value === 'string'),
    ),
    expectedWarnings = (plan.warnings || [])
      .filter((value) => typeof value === 'string' && !auditLimits.has(value))
      .slice(0, 12);
  check(
    JSON.stringify(
      await evaluate(
        "[...document.getElementById('trafficWarnings').children].map(item=>item.textContent)",
      ),
    ) === JSON.stringify(expectedWarnings),
    'exact audit limitations are not duplicated among warnings, while every other bounded warning is retained',
  );
  check(
    await evaluate(
      `document.getElementById('trafficPlanExport').getAttribute('href')==='/api/traffic/plans/${record.id}/bundle.zip'&&!document.getElementById('trafficRevalidate').disabled`,
    ),
    'real selected plan offers its own bounded export and explicit re-audit action',
  );
  check(
    await evaluate(
      "document.getElementById('trafficAuditReasons').textContent.includes('conformité COLREG complète')",
    ),
    'limited geometric result never claims full COLREG certification',
  );
  await evaluate("document.getElementById('trafficAuditBadge').scrollIntoView({block:'center'})");
  await shot('actual-library-audit.png');
  await set('trafficTime', Math.min(70, plan.timeline.endSeconds));
  await evaluate("document.getElementById('trafficMap').scrollIntoView({block:'center'})");
  check(
    await evaluate(
      "document.querySelectorAll('#trafficMap polyline').length===33&&document.querySelectorAll('.traffic-object').length===32",
    ),
    'real map shows 32 actors and the observer without starting a simulation',
  );
  await shot('actual-library-map.png');
  await send('Page.reload', { ignoreCache: true });
  await waitFor(
    `document.getElementById('trafficPlanChoice').options.length===${library.plans.length + 1}`,
  );
  await set('trafficPlanChoice', record.id, 'change');
  await waitFor(
    "document.getElementById('trafficAuditBadge').textContent==='Contrôles limités satisfaits'&&!document.getElementById('trafficPlanChoice').disabled",
  );
  check(
    await evaluate(`document.getElementById('trafficPlanChoice').value==='${record.id}'`),
    'stored plan remains selectable after reloading the installed dashboard',
  );
  await send('Emulation.setDeviceMetricsOverride', {
    width: 430,
    height: 1050,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await evaluate('window.scrollTo(0,0)');
  check(
    await evaluate('document.documentElement.scrollWidth<=innerWidth'),
    'actual library and generator have no mobile horizontal overflow',
  );
  await shot('actual-library-mobile.png');
  const afterLibrary = await get('/api/traffic/plans'),
    afterSource = await get('/api/traffic/plan'),
    afterPlan = await get('/api/traffic/plan?planId=' + record.id),
    afterRegistry = await get('/api/engines');
  check(
    JSON.stringify(afterLibrary.plans.map((item) => [item.id, item.planSha256])) ===
      JSON.stringify(library.plans.map((item) => [item.id, item.planSha256])) &&
      afterSource.baseSha256 === source.baseSha256 &&
      afterPlan.baseSha256 === plan.baseSha256,
    'library records, selected plan and legacy source hashes are unchanged',
  );
  check(
    afterRegistry.selectedEngine?.id === registry.selectedEngine?.id &&
      !!registry.selectedEngine?.id,
    'persisted project engine profile is unchanged',
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
    'no browser JavaScript or request safety errors',
  );
  const result = {
    passed: true,
    checks,
    evidence:
      'Actual installed UI and unmocked GETs only; SQLite created by parent separately, no native runtime or writes from this browser.',
    planId: record.id,
    actorCount: plan.actors.length,
    audit: {
      pairChecks: plan.audit.pairChecks,
      limitedEncounters: encounters,
      excludedPairs: excluded,
      fullColregCompliance: false,
    },
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
