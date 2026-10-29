'use strict';
const { uiFile, coreRoot } = require('./support/paths.cjs');

const assert = require('node:assert/strict');
const {
  functionSource,
  hasStringProperty,
  hasFetchBase,
  hasCssDeclaration,
} = require('./support/source_contract_helpers.cjs');

const source = `
// function fake() { return 'not code'; }
const description = "function fake() {}";
(() => {
function real (
  value
) { return value + 1; }
const request = { "X-LOTUSim-Settings": '1' };
fetch (
  "/api/settings/" + kind,
  request
);
})();`;

assert.equal(
  functionSource(source, 'real').trim(),
  'function real (\n  value\n) { return value + 1; }',
);
assert.throws(() => functionSource(source, 'fake'), /Known function declaration/);
assert.ok(hasStringProperty(source, 'X-LOTUSim-Settings', '1'));
assert.ok(
  !hasStringProperty("const text = \"'X-LOTUSim-Settings':'1'\"", 'X-LOTUSim-Settings', '1'),
);
assert.ok(
  !hasStringProperty('const request = {"X-LOTUSim-Settings": "0"}', 'X-LOTUSim-Settings', '1'),
);
assert.ok(hasFetchBase(source, '/api/settings/', 'kind'));
assert.ok(
  !hasFetchBase('const text = "fetch(\'/api/settings/\'+kind)";', '/api/settings/', 'kind'),
);
assert.ok(!hasFetchBase('fetch("https://outside.invalid/" + kind)', '/api/settings/', 'kind'));
assert.ok(
  hasCssDeclaration(
    '.traffic-legend-sea {\n background: teal;\n}',
    '.traffic-legend-sea',
    'background',
  ),
);
assert.ok(
  !hasCssDeclaration(
    '/* .traffic-legend-sea{background:teal} */ .other { color: teal; }',
    '.traffic-legend-sea',
    'background',
  ),
);
assert.ok(
  !hasCssDeclaration('.traffic-legend-sea { color: teal; }', '.traffic-legend-sea', 'background'),
);
console.log('11 syntax-based source contract checks passed');
