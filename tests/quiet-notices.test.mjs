import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = name => readFileSync(new URL(`../${name}`, import.meta.url), 'utf8');
class Element {
  constructor(tag, className = '', text = '') { Object.assign(this, { tag, className, text, children: [] }); }
  append(...children) { this.children.push(...children); }
}

test('reader warning receipts are retained in a closed disclosure, never banner paragraphs', () => {
  const script = source('js/reader.js');
  const context = vm.createContext({ node: (...args) => new Element(...args) });
  vm.runInContext(script.slice(script.indexOf('  function appendWarnings('), script.indexOf('  function chronologyClaim(')), context);
  const host = new Element('div');
  context.appendWarnings(host, ['Synthetic scope note', null, { source: 'synthetic receipt' }, 'Third note', 'Fourth note']);
  assert.equal(host.children.length, 1);
  const details = host.children[0];
  assert.equal(details.tag, 'details'); assert.equal(details.open, undefined);
  assert.equal(details.children[0].tag, 'summary'); assert.equal(details.children[0].text, 'Details');
  assert.equal(details.children.length, 5);
  assert.equal(details.children[2].text, '{"source":"synthetic receipt"}');
  assert.ok(details.children.every(item => item.className !== 'warning'));
  context.appendWarnings(host, [null, '']); assert.equal(host.children.length, 1);
});

test('notice and caution styles resolve to white and theme blue, not warning colors', () => {
  const css = source('css/reader.css');
  const notice = css.slice(css.indexOf('/* Quiet notices:'));
  assert.match(notice, /\.warning,\.error-message\{[^}]*background:#fff;color:var\(--sea\)/);
  assert.match(notice, /\.quality-tag\.caution\{[^}]*background:#fff;color:var\(--sea\)/);
  assert.match(notice, /\.notice-details>summary\{color:var\(--sea\)/);
});

test('projection method and warnings are under optional details while legend stays visible', () => {
  const script = source('js/usage-space.js');
  assert.match(script, /element\('details', 'mus-notes'\)/);
  assert.match(script, /notes.append\(element\('summary', '', 'Projection details'\), method, warnings\)/);
  assert.match(script, /foot.append\(notes, legend\)/);
  assert.doesNotMatch(script, /mus-warnings[^}]*#715121/);
});

test('dictionary and inventory caveats are disclosures, with a concise nearby-match status', () => {
  const script = source('js/reader.js');
  assert.match(script, /appendWarnings\(section, \['Machine-extracted dictionary reference/);
  assert.match(script, /appendWarnings\(section, \['Forms recorded under each source lemma/);
  assert.match(script, /'candidate-meta-label', 'No exact source match\.'/);
  assert.match(script, /appendWarnings\(absence, \['Only nearby spellings/);
  assert.doesNotMatch(script, /card.append\(live, node\('p', 'candidate-reason', 'Live page may differ/);
});
