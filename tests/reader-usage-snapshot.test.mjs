import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');

function harness() {
  class Element {
    constructor() { this.children = []; this.value = ''; this.checked = false; this.hidden = false; this.options = [];
      const classes = new Set();
      this.classList = { add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name) };
    }
    append(...children) { this.children.push(...children); }
    querySelectorAll() { return this.children.filter(child => child.result); }
    scrollIntoView() {}
    focus() {}
  }
  const ui = Object.fromEntries(['authorFilter', 'edition', 'language', 'order', 'reference', 'searchInput',
    'results', 'resultsList', 'resultsHeading', 'resultsSummary', 'moreResults'].map(key => [key, new Element()]));
  ui.order.value = 'relevance';
  const state = { search: null, displayedSearch: null, searchSequence: 0 }, pending = [];
  let mode = 'hybrid';
  const context = vm.createContext({ ui, state, formMode: () => mode,
    clear: element => { element.children = []; }, loadDictionaryPreview() {},
    node: (...args) => ({ args }), renderResult: record => ({ result: true, id: record.id }),
    appendWarnings() {}, describeCount: (n, label) => `${n} ${label}`, errorText: error => error.message,
    writeSearchUrl: () => 'https://example.test/', location: { href: 'https://example.test/' }, history: { replaceState() {} },
    api: (path, params) => new Promise((resolve, reject) => pending.push({ params, resolve, reject })) });
  vm.runInContext(source.slice(source.indexOf('  function snapshotSearch('), source.indexOf('  function addInspectorSection(')), context);
  return { ui, state, pending, setMode: value => { mode = value; },
    search: vm.runInContext('search', context), usage: vm.runInContext('usageSnapshot', context) };
}
const response = id => ({ results: [{ id }], total: 1, warnings: [] });

test('usage keeps one completed displayed search despite unsent input/filter changes', async () => {
  const h = harness();
  h.ui.authorFilter.value = 'Ibycus'; h.ui.language.value = 'grc'; h.ui.edition.value = 'Edition';
  h.ui.reference.checked = true; h.ui.order.value = 'chronological';
  const request = h.search('saved phrase', 'exact');
  h.pending[0].resolve(response('one')); await request;
  h.ui.authorFilter.value = 'Other'; h.ui.language.value = 'ell'; h.ui.reference.checked = false;
  h.setMode('themes');
  const scope = h.usage('unsent phrase');
  assert.equal(scope.q, 'saved phrase'); assert.equal(scope.mode, 'words'); assert.equal(scope.match, 'exact');
  assert.equal(scope.author, 'Ibycus'); assert.equal(scope.language, 'grc'); assert.equal(scope.edition, 'Edition');
  assert.equal(scope.include_reference, true); assert.equal(scope.order, 'chronological');
  assert.match(scope.scope_notice, /Current inputs differ/);
  assert.ok(Object.isFrozen(h.state.displayedSearch));
  h.ui.results.hidden = true;
  assert.equal(h.usage('selected phrase').q, 'selected phrase');
  assert.equal(h.usage('selected phrase').language, 'ell');
  assert.equal(h.usage('selected phrase').mode, 'themes');
});

test('out-of-order responses and failed new requests never promote a stale snapshot', async () => {
  const h = harness();
  const old = h.search('old', 'exact');
  const fresh = h.search('fresh', 'forms');
  h.pending[1].resolve(response('fresh')); await fresh;
  h.pending[0].resolve(response('old')); await old;
  assert.equal(h.usage('edited').q, 'fresh');
  const failed = h.search('failed', 'themes');
  assert.equal(h.state.displayedSearch, null);
  h.pending[2].reject(new Error('Synthetic failure')); await failed;
  assert.equal(h.state.displayedSearch, null);
  assert.equal(h.usage('current').scope_origin, 'Current query and controls');
});

test('a failed or outdated pagination request retains only the current successful displayed scope', async () => {
  const h = harness();
  const first = h.search('first', 'forms'); h.pending[0].resolve(response('first')); await first;
  const page = h.search('first', 'forms', true);
  const fresh = h.search('new', 'themes'); h.pending[2].resolve(response('new')); await fresh;
  h.pending[1].resolve(response('old page')); await page;
  assert.equal(h.usage('edited').q, 'new');
  const failedPage = h.search('new', 'themes', true); h.pending[3].reject(new Error('Synthetic failure')); await failedPage;
  assert.equal(h.usage('edited').q, 'new');
});
