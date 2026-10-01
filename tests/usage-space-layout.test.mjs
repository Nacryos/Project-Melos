import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../js/usage-space.js', import.meta.url), 'utf8');
const styles = [];
const context = vm.createContext({ STYLE_ID: 'fixture-style', element: () => ({}),
  document: { getElementById: () => null, head: { append: style => styles.push(style.textContent) } } });
vm.runInContext(source.slice(source.indexOf('  function injectStyle('), source.indexOf('  function colorFor(')), context);
vm.runInContext('injectStyle()', context);
const css = styles[0], desktop = css.slice(0, css.indexOf('@media'));
const rule = (text, selector) => text.match(new RegExp(`\\${selector}\\s*\\{([^}]+)\\}`))[1];

// Structural CSS regressions; real viewport layout is checked in browser QA.
test('short dialog confines middle-row overflow instead of painting plot controls over its footer', () => {
  assert.match(rule(desktop, '.mus-dialog'), /grid-template-rows:\s*auto minmax\(0, 1fr\) auto/);
  assert.match(rule(desktop, '.mus-main'), /min-height:\s*0/);
  assert.match(rule(desktop, '.mus-main'), /grid-template-rows:\s*minmax\(0, 1fr\)/);
  assert.match(rule(desktop, '.mus-main'), /overflow:\s*auto/);
  assert.match(rule(desktop, '.mus-visual'), /grid-template-rows:\s*minmax\(120px, 1fr\) auto/);
  assert.match(rule(desktop, '.mus-plot'), /min-height:\s*0/);
  assert.doesNotMatch(rule(desktop, '.mus-plot'), /min-height:\s*240px/);
  assert.match(rule(desktop, '.mus-foot'), /overflow:\s*auto/);
});

test('narrow layouts retain usable plot and detail rows within the same contained scroll area', () => {
  const mobile = css.slice(css.indexOf('@media (max-width: 760px)'));
  assert.match(rule(mobile, '.mus-main'), /grid-template-columns:\s*1fr/);
  assert.match(rule(mobile, '.mus-main'), /grid-template-rows:\s*minmax\(280px, 44%\) minmax\(260px, 1fr\)/);
  assert.doesNotMatch(rule(mobile, '.mus-main'), /overflow:\s*(visible|hidden)/);
  assert.match(rule(desktop, '.mus-detail, .mus-list-wrap'), /overflow:\s*auto/);
});
