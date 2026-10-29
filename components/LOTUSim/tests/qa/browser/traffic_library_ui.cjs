/* Browser-only library/revision fixtures; all mutation requests intercepted in memory. */
'use strict';
const { uiFile, coreRoot } = require('../../web/support/paths.cjs');
const fs = require('node:fs'),
  path = require('node:path'),
  cp = require('node:child_process'),
  assert = require('node:assert/strict');
const origin = 'http://127.0.0.1:8766',
  root = coreRoot,
  ui = path.join(root, 'tools', 'ops_dashboard_ui'),
  output = path.join(root, 'artifacts', 'qa', 'traffic-library-ui');
fs.mkdirSync(output, { recursive: true });
const profile = fs.mkdtempSync('/private/tmp/lotusim-traffic-library-ui-'),
  pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  clone = (value) => JSON.parse(JSON.stringify(value));
const math = require(uiFile(ui, 'traffic.js')),
  records = [],
  database = new Map(),
  pending = new Map(),
  events = [],
  writes = [],
  fixtureErrors = [],
  screenshots = [];
let source,
  catalog,
  browser,
  connection,
  sequence = 0,
  planSequence = 0,
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
        reject(Error('CDP timeout ' + method));
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
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (await evaluate(expression)) return;
    await pause(100);
  }
  throw Error('Timed out ' + expression);
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
  const result = await send('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: false,
    }),
    file = path.join(output, name);
  fs.writeFileSync(file, Buffer.from(result.data, 'base64'));
  screenshots.push(file);
}
function store(name, kind, parentId = null, ready = true, base = source, metadata = {}) {
  const id = '00000000-0000-4000-8000-' + String(++planSequence).padStart(12, '0');
  const record = {
    id,
    name,
    kind,
    parentId,
    ready,
    status: ready ? 'ready' : 'needs_revalidation',
    auditStatus: ready ? 'approved' : 'requires_revalidation',
    actorCount: base.actors.length,
    durationSeconds: base.timeline.durationSeconds,
    createdAt: new Date().toISOString(),
    metadata,
    applied: false,
  };
  const preview = {
    ...clone(base),
    planId: id,
    record,
    audit: {
      approved: ready,
      fullColregCompliance: false,
      notCertified: true,
      limitations: [
        'Fixture UI : aucun audit physique ni certification réellement exécuté par ce test.',
      ],
    },
    applied: false,
  };
  records.unshift(record);
  database.set(id, preview);
  return {
    id,
    planId: id,
    record,
    preview,
    files: ['plan.json', 'audit.json', 'instructions.txt'],
    applied: false,
  };
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
    writes.push({ method: request.method, path: url.pathname, body, headers: request.headers });
    if (request.method === 'POST' && url.pathname === '/api/settings/validate') {
      const campaign = JSON.parse(body);
      return fulfill({ valid: true, campaign, errors: [], warnings: [] });
    }
    if (request.method === 'POST' && url.pathname === '/api/traffic/generate') {
      const input = JSON.parse(body),
        base = clone(source);
      if (input.campaign) {
        const block = input.campaign.blocks.find((block) => block.id === input.blockId);
        base.actors = block.objects.flatMap((row) =>
          Array.from({ length: row.count }, (_, n) => {
            const actor = clone(
              source.actors.find((actor) => actor.model === row.model) || source.actors[0],
            );
            actor.id = 'Block_' + row.id + '_' + n;
            return actor;
          }),
        );
      }
      return fulfill(
        store(input.name, 'generated', null, true, base, {
          blockId: input.blockId,
          actionProfile: input.actionProfile,
          speedPolicy: input.speedPolicy || 'catalogue',
        }),
      );
    }
    if (request.method === 'POST' && url.pathname === '/api/traffic/drafts') {
      const input = JSON.parse(body),
        base = clone(database.get(input.planId) || source);
      base.baseSha256 = 'c'.repeat(64);
      for (const change of input.changes) {
        const actor = base.actors.find((actor) => actor.id === change.actorId);
        Object.assign(actor, change);
        actor.points = actor.points.map((point) => math.position(actor, point.timeSeconds));
      }
      return fulfill(store(input.name, 'manual_revision', input.planId, false, base));
    }
    if (
      request.method === 'POST' &&
      /^\/api\/traffic\/plans\/[a-f0-9-]+\/revalidate$/.test(url.pathname)
    ) {
      const id = url.pathname.split('/')[4];
      return fulfill(store('QA · réévaluation bornée', 'revalidation', id, true, database.get(id)));
    }
    return fulfill({ message: 'Every other UI QA mutation is blocked.' }, 'application/json', 403);
  }
  if (url.origin !== origin)
    return send('Fetch.failRequest', { requestId, errorReason: 'BlockedByClient' });
  if (url.pathname === '/')
    return fulfill(fs.readFileSync(uiFile(ui, 'index.html'), 'utf8'), 'text/html');
  if (['/settings.js', '/traffic.js', '/traffic.css'].includes(url.pathname))
    return fulfill(
      fs.readFileSync(uiFile(ui, url.pathname.slice(1)), 'utf8'),
      url.pathname.endsWith('.js') ? 'text/javascript' : 'text/css',
    );
  if (url.pathname === '/api/traffic/plans')
    return fulfill({ schema: 'lotusim-traffic-library-1', plans: records });
  if (url.pathname === '/api/traffic/plan')
    return fulfill(
      url.searchParams.has('planId') ? database.get(url.searchParams.get('planId')) : source,
    );
  if (url.pathname === '/api/settings/catalog') return fulfill(catalog);
  return send('Fetch.continueRequest', { requestId });
}
(async () => {
  source = await (await fetch(origin + '/api/traffic/plan')).json();
  catalog = await (await fetch(origin + '/api/settings/catalog')).json();
  check(
    source.available && source.actors.length === 32,
    'actual existing plan provides a read-only base fixture',
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
      const task = pending.get(item.id);
      pending.delete(item.id);
      item.error ? task.reject(Error(JSON.stringify(item.error))) : task.resolve(item.result);
    } else {
      events.push(item);
      if (item.method === 'Fetch.requestPaused')
        paused(item).catch((error) => fixtureErrors.push(error.stack));
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
    "!document.getElementById('trafficWorkspace').hidden&&document.querySelectorAll('.traffic-object').length===32",
  );
  check(writes.length === 0, 'opening the source/library performs no write');
  await set('trafficGenerateName', 'QA · trafic coopératif');
  await set('trafficGenerateSeed', 42);
  await set('trafficGenerateDuration', 180);
  await set('trafficGenerateProfile', 'parallel', 'change');
  await click('trafficGenerate');
  const generated = '00000000-0000-4000-8000-000000000001';
  await waitFor(
    `document.getElementById('trafficPlanChoice').value==='${generated}'&&!document.getElementById('trafficPlanChoice').disabled`,
  );
  check(
    await evaluate(
      "document.getElementById('trafficAuditBadge').textContent==='Contrôles limités satisfaits'&&document.getElementById('trafficLibraryCount').textContent.includes('1 plans')",
    ),
    'generated plan is saved in the fixture library and automatically displayed',
  );
  await evaluate('window.scrollTo(0,0)');
  await shot('library-generated-plan.png');
  const actor = source.actors.find(
    (actor) => actor.domain === 'sea' && actor.editable && actor.maxSpeedMps > 0,
  );
  await evaluate(
    `[...document.querySelectorAll('.traffic-object')].find(button=>button.dataset.actorId===${JSON.stringify(actor.id)}).click()`,
  );
  await set('trafficEast', actor.centerENU.eastM + 25);
  await click('trafficPreviewEdit');
  await click('trafficSave');
  const revision = '00000000-0000-4000-8000-000000000002';
  await waitFor(
    `document.getElementById('trafficPlanChoice').value==='${revision}'&&!document.getElementById('trafficRevalidate').disabled`,
  );
  check(
    await evaluate(
      "document.getElementById('trafficAuditBadge').textContent==='Révalidation nécessaire'&&document.getElementById('trafficPlanExport').textContent.includes('sans YAML')",
    ),
    'manual child revision is selected and visibly loses previous audit approval',
  );
  await evaluate("document.getElementById('trafficAuditBadge').scrollIntoView({block:'center'})");
  await shot('library-manual-revision.png');
  await click('trafficRevalidate');
  const audited = '00000000-0000-4000-8000-000000000003';
  await waitFor(
    `document.getElementById('trafficPlanChoice').value==='${audited}'&&!document.getElementById('trafficRevalidate').disabled`,
  );
  check(
    database.get(audited).baseSha256 === database.get(revision).baseSha256 &&
      records[0].parentId === revision,
    'reaudit creates a new metadata revision without changing trajectory hash',
  );
  await evaluate("document.getElementById('trafficAuditBadge').scrollIntoView({block:'center'})");
  await shot('library-reaudited-revision.png');
  await send('Page.reload', { ignoreCache: true });
  await waitFor(
    "!document.getElementById('trafficWorkspace').hidden&&document.getElementById('trafficPlanChoice').options.length===4",
  );
  await set('trafficPlanChoice', audited, 'change');
  await waitFor(
    "document.getElementById('trafficAuditBadge').textContent==='Contrôles limités satisfaits'&&!document.getElementById('trafficPlanChoice').disabled",
  );
  check(
    await evaluate(`document.getElementById('trafficPlanChoice').value==='${audited}'`),
    'all three persisted fixtures remain selectable after page reload',
  );
  await evaluate("document.querySelector('[data-route=settings]').click()");
  await waitFor("!document.getElementById('settingsEditor').hidden");
  await set('settingsTrafficDuration', 0);
  const beforeValidation = writes.length;
  await click('settingsValidate');
  await waitFor(
    `document.getElementById('settingsNotice').textContent.includes('Configuration vérifiée')`,
  );
  check(
    writes.length === beforeValidation + 1 && writes.at(-1).path === '/api/settings/validate',
    'invalid continuous duration does not block the independent-image validation path',
  );
  const block = catalog.defaults.blocks[0];
  await set('settingsTrafficBlock', block.id, 'change');
  await set('settingsTrafficDuration', 180);
  await set('settingsTrafficProfile', 'open_water', 'change');
  await set('settingsTrafficSpeedPolicy', 'requested', 'change');
  await evaluate(
    "document.querySelector('.traffic-settings-panel').scrollIntoView({block:'center'})",
  );
  await shot('settings-selected-block-generation.png');
  await click('settingsGenerateTraffic');
  const fromSettings = '00000000-0000-4000-8000-000000000004';
  await waitFor(
    `location.hash==='#traffic'&&document.getElementById('trafficPlanChoice').value==='${fromSettings}'&&!document.getElementById('trafficPlanChoice').disabled`,
  );
  const request = JSON.parse(writes.findLast((item) => item.path === '/api/traffic/generate').body);
  check(
    request.blockId === block.id &&
      request.campaign.blocks.length === catalog.defaults.blocks.length &&
      request.speedPolicy === 'requested' &&
      request.headingPolicy === 'profile',
    'settings sends the actual validated campaign plus one explicit block and policies',
  );
  check(
    await evaluate(
      "document.getElementById('trafficAuditDetail').textContent.includes('Campagne maritime manuelle')",
    ),
    'settings generation navigates to its newly stored plan, not the previous selection',
  );
  check(
    !writes.some((item) => item.path === '/api/settings/prepare' || item.path.includes('/apply')),
    'no independent-image prepare or runtime apply endpoint is touched',
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
    'library and generator have no mobile horizontal overflow',
  );
  await shot('library-mobile.png');
  check(
    writes.every(
      (item) =>
        item.path === '/api/settings/validate' ||
        Object.entries(item.headers).some(
          ([key, value]) => key.toLowerCase() === 'x-lotusim-traffic' && value === '1',
        ),
    ),
    'every generated-plan mutation carries the dedicated intent header',
  );
  const errors = events
    .filter((item) => item.method === 'Runtime.exceptionThrown')
    .map(
      (item) =>
        item.params.exceptionDetails?.exception?.description || item.params.exceptionDetails?.text,
    );
  check(
    errors.length === 0 && fixtureErrors.length === 0,
    'no browser JavaScript or fixture errors',
  );
  const result = {
    passed: true,
    checks,
    evidence:
      'Browser-only generator/library/revision responses; no production writes, SQLite changes or native runtime.',
    realServerMutations: 0,
    interceptedWrites: writes.map((item) => ({ method: item.method, path: item.path })),
    errors,
    screenshots,
  };
  fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
})()
  .catch((error) => {
    const result = { passed: false, checks, error: error.stack, fixtureErrors, screenshots };
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
