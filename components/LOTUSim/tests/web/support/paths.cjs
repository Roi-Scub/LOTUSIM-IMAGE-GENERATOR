/* Shared test-only source paths. Public URLs and disk layout are separate contracts. */
'use strict';

const path = require('node:path');
const coreRoot = path.resolve(__dirname, '../../..');
const routes = require('../../../tools/ops_dashboard_ui/resources.json');

function uiFile(root, name) {
  const route = name.startsWith('/') ? name : '/' + name;
  const relative = routes[route] || name;
  const directory = path.resolve(root);
  const target = path.resolve(directory, relative);
  if (!target.startsWith(directory + path.sep)) throw Error('UI source path escapes its root');
  return target;
}

module.exports = { coreRoot, uiFile };
