import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../js/usage-space.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [], style: {}, dataset: {} }); }
  append(...children) { this.children.push(...children); }
  prepend(...children) { this.children.unshift(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
  addEventListener() {}
  get childElementCount() { return this.children.length; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.text = value; this.children = []; }
}
const context = vm.createContext({ element: (...args) => new Element(...args), dateLabel: () => '', safeUrl: () => null, URLSearchParams });
vm.runInContext(source.slice(source.indexOf('  function colorFor('), source.indexOf('  function open(')), context);
vm.runInContext('draw = () => {}', context);
const request = vm.runInContext('usageRequest', context), populate = vm.runInContext('populate', context);
const detail = vm.runInContext('showDetail', context), label = vm.runInContext('scopeLabel', context);

test('usage request serializes every search constraint including false flags', () => {
  const scope = { mode: 'words', match: 'exact', language: 'grc', edition: 'A&B edition',
    include_reference: false, order: 'chronological', commentary_assisted: false };
  const params = request('Greek & phrase', 'Ibycus', scope);
  assert.deepEqual(Object.fromEntries(params), { q: 'Greek & phrase', author: 'Ibycus', limit: '80',
    mode: 'words', match: 'exact', language: 'grc', edition: 'A&B edition',
    include_reference: 'false', order: 'chronological', commentary_assisted: 'false' });
  assert.equal(request('q', '', { mode: 'themes', include_reference: true }).get('include_reference'), 'true');
  assert.equal(request('q', '', {}).get('mode'), 'forms'); // legacy callers only
});

test('scope labels distinguish exact, language, edition and reference constraints', () => {
  const text = label({ mode: 'words', match: 'exact', language: 'ell', edition: 'Synthetic edition',
    include_reference: true, order: 'chronological', scope_origin: 'Last successfully displayed search' });
  for (const expected of ['Last successfully displayed search', 'Exact words', 'Modern Greek',
    'Synthetic edition', 'Reference/uncertain records included', 'Chronological order']) assert.ok(text.includes(expected));
});

test('projection presents upstream and changed-control warnings, omission counts and exact record labels', () => {
  const state = Object.fromEntries(['status', 'count', 'method', 'warnings', 'list', 'legend', 'detail', 'scope'].map(key => [key, new Element('div')]));
  state.requestScope = { scope_origin: 'Last successfully displayed search', scope_notice: 'Current inputs differ; preserved snapshot.' };
  const point = { id: 'synthetic', x: 0, y: 0, z: 0, author: 'Synthetic translator',
    language: 'ell', kind: 'translation', quality: 'needs_review', citation: 'Synthetic citation', text: 'Synthetic text' };
  populate(state, { points: [point, { id: 'invalid', x: null, y: 0, z: 0 }],
    retrieved_count: 4, plotted_count: 2, omitted_count: 2, scope: { mode: 'words', match: 'exact', language: 'ell' },
    warnings: ['Synthetic upstream quality warning'], method: 'Synthetic exact wording' });
  assert.equal(state.count.textContent, '1 plotted · 4 retrieved · 3 omitted');
  assert.match(state.warnings.textContent, /Current inputs differ/);
  assert.match(state.warnings.textContent, /Synthetic upstream quality warning/);
  assert.match(state.warnings.textContent, /coordinates or ID were invalid/);
  assert.match(state.scope.textContent, /Last successfully displayed search/);
  assert.match(state.list.textContent, /Modern Greek · translation · Needs review/);
  detail(state, point, false);
  assert.match(state.detail.textContent, /Synthetic translator/);
  assert.match(state.detail.textContent, /Modern Greek · translation · Needs review/);
});

test('a genuine zero-result search is distinguished from unusable projected coordinates', () => {
  const state = Object.fromEntries(['status', 'count', 'method', 'warnings', 'list', 'legend', 'detail'].map(key => [key, new Element('div')]));
  populate(state, { points: [], retrieved_count: 0, plotted_count: 0, omitted_count: 0 });
  assert.equal(state.status.textContent, 'No passages matched these search filters.');
  populate(state, { points: [{ id: 'invalid', x: null, y: 0, z: 0 }], retrieved_count: 1 });
  assert.equal(state.status.textContent, 'No passages with usable coordinates were returned for this query.');
});
