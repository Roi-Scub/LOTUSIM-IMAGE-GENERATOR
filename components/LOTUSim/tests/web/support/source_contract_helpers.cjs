'use strict';

// Development-only syntax checks. Whitespace and quote style are not contracts.
const assert = require('node:assert/strict');
const { parse } = require('@babel/parser');
const postcss = require('postcss');

function syntax(source) {
  return parse(source, { sourceType: 'unambiguous' });
}

function visit(node, predicate) {
  if (!node || typeof node !== 'object') return false;
  if (predicate(node)) return true;
  return Object.values(node).some((value) =>
    Array.isArray(value)
      ? value.some((child) => visit(child, predicate))
      : value && typeof value === 'object' && visit(value, predicate),
  );
}

function functionSource(source, name) {
  let declaration;
  visit(syntax(source), (node) => {
    if (node.type !== 'FunctionDeclaration' || node.id?.name !== name) return false;
    declaration = node;
    return true;
  });
  assert.ok(declaration, 'Known function declaration: ' + name);
  return source.slice(declaration.start, declaration.end);
}

function hasStringProperty(source, name, value) {
  return visit(
    syntax(source),
    (node) =>
      node.type === 'ObjectProperty' &&
      !node.computed &&
      (node.key.name === name || node.key.value === name) &&
      node.value.type === 'StringLiteral' &&
      node.value.value === value,
  );
}

function hasFetchBase(source, prefix, suffixName) {
  return visit(syntax(source), (node) => {
    if (
      node.type !== 'CallExpression' ||
      node.callee.type !== 'Identifier' ||
      node.callee.name !== 'fetch'
    )
      return false;
    const argument = node.arguments[0];
    return (
      argument?.type === 'BinaryExpression' &&
      argument.operator === '+' &&
      argument.left.type === 'StringLiteral' &&
      argument.left.value === prefix &&
      argument.right.type === 'Identifier' &&
      argument.right.name === suffixName
    );
  });
}

function hasCssDeclaration(source, selector, property) {
  let found = false;
  postcss.parse(source).walkRules((rule) => {
    if (!rule.selectors.includes(selector)) return;
    rule.walkDecls(property, () => {
      found = true;
    });
  });
  return found;
}

module.exports = { functionSource, hasStringProperty, hasFetchBase, hasCssDeclaration };
