import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div', cls = '', content = '') {
    Object.assign(this, { tag, cls, content, children: [], value: '', dataset: {}, checked: false });
    const classes = new Set(cls.split(/\s+/).filter(Boolean));
    this.classList = { add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name) };
  }
  append(...children) { this.children.push(...children); }
  after(element) { this.afterElement = element; }
  setAttribute(key, value) { (this.attributes ||= {})[key] = value; }
  getAttribute(key) { return this.attributes?.[key] ?? null; }
  removeAttribute(key) { delete (this.attributes ||= {})[key]; }
  replaceChildren() { this.children = []; this.content = ''; }
  querySelectorAll(selector) { return this.children.filter(child => child.cls === selector.slice(1)); }
  scrollIntoView() {}
  focus() {}
  get options() { return this.children; }
  get firstChild() { return this.children[0]; }
  get textContent() { return this.content + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.content = value; this.children = []; }
}
function harness() {
  const ui = Object.fromEntries(['authorFilter', 'edition', 'language', 'order', 'reference', 'searchInput', 'searchForm', 'dictionaryPreview',
    'formsOptions', 'formsRelation', 'formsSlop', 'formsSlopLabel', 'formsNote',
    'results', 'resultsList', 'resultsHeading', 'resultsSummary', 'moreResults'].map(key => [key, new Element()]));
  for (const [name, values] of Object.entries({ authorFilter: ['', 'Ibycus', 'Sappho'], edition: ['', 'Fixture edition'],
    language: ['', 'grc', 'eng'], order: ['relevance', 'chronological'] })) {
    for (const value of values) { const option = new Element('option', '', value); option.value = value; ui[name].append(option); }
    ui[name].value = values[0];
  }
  const state = { search: null, searchSequence: 0 }, pending = [], visited = [], previews = [];
  ui.formsRelation.value = 'ordered'; ui.formsSlop.value = '0';
  const location = { href: 'https://example.test/?id=fragment-old&campaign=keep#reader' };
  let mode = 'hybrid';
  const context = vm.createContext({
    ui, state, URL, URLSearchParams, location,
    history: { replaceState(a, b, url) { location.href = String(url); visited.push(String(url)); } },
    formMode: () => mode, setFormMode: value => { mode = value; },
    node: (tag, cls, content) => new Element(tag, cls, content), clear: element => element.replaceChildren(),
    loadDictionaryPreview(query) { previews.push(query); }, describeCount: (number, label) => `${number} ${label}`,
    renderResult: record => new Element('button', 'result-button', record.id),
    appendWarnings: (host, warnings) => { for (const warning of warnings || []) host.append(new Element('p', '', warning)); },
    errorText: error => error.message,
    api: (path, params) => new Promise((resolve, reject) => pending.push({ path, params, resolve, reject }))
  });
  vm.runInContext(script.slice(script.indexOf('  function readSearchUrl('), script.indexOf('  function addInspectorSection(')), context);
  return { ui, state, pending, visited, previews, location, mode: () => mode,
    read: vm.runInContext('readSearchUrl', context), write: vm.runInContext('writeSearchUrl', context),
    restore: vm.runInContext('restoreSearchUrl', context), search: vm.runInContext('search', context), context };
}
const response = id => ({ results: [{ id }], total: 5, warnings: [] });

test('search discloses supplied normalized Greek wording as text once, without inventing a transliteration', async () => {
  const h = harness();
  const first = h.search('eri men ai te kudoniai');
  h.pending[0].resolve({ ...response('one'), transliteration_phrase: {
    matched_greek_phrases: ['ηρι μεν αι τε κυδωνιαι', 'ηρι μεν αι τε κυδωνιαι', null, '']
  } });
  await first;
  const notices = () => h.ui.resultsList.children.filter(item => item.cls.includes('transliteration-wording'));
  assert.equal(notices().length, 1);
  assert.match(notices()[0].textContent, /Matched Greek wording: ηρι μεν αι τε κυδωνιαι/);
  assert.match(notices()[0].textContent, /normalized for matching, not the source's accents or spelling/);
  const more = h.search('eri men ai te kudoniai', 'hybrid', true);
  h.pending[1].resolve({ ...response('two'), transliteration_phrase: { matched_greek_phrases: ['ηρι μεν αι τε κυδωνιαι'] } });
  await more;
  assert.equal(notices().length, 1);
  const ordinary = h.search('rose'); h.pending[2].resolve(response('three')); await ordinary;
  assert.equal(notices().length, 0);
  const markup = h.search('synthetic');
  h.pending[3].resolve({ ...response('four'), transliteration_phrase: { matched_greek_phrases: ['<b>source text</b>'] } });
  await markup;
  assert.match(notices()[0].textContent, /<b>source text<\/b>/);
  assert.equal(notices()[0].children.length, 0);
});

test('all executed search filters round-trip while passage id, unknown parameters and hash survive', () => {
  const h = harness();
  const original = { query: 'love like an old racehorse', mode: 'themes', author: 'Ibycus',
    edition: 'Fixture edition', language: 'grc', order: 'chronological', include_reference: true };
  const url = h.write(h.location.href, original);
  assert.equal(url.searchParams.get('id'), 'fragment-old');
  assert.equal(url.searchParams.get('campaign'), 'keep');
  assert.equal(url.hash, '#reader');
  const saved = h.restore(url.searchParams);
  for (const key of Object.keys(original)) assert.equal(saved[key], original[key]);
  assert.equal(h.ui.authorFilter.value, 'Ibycus');
  assert.equal(h.ui.edition.value, 'Fixture edition');
  assert.equal(h.ui.language.value, 'grc');
  assert.equal(h.ui.order.value, 'chronological');
  assert.equal(h.ui.reference.checked, true);
  assert.equal(h.mode(), 'themes');
});

test('legacy query-only links retain default mode without fabricating filters', () => {
  const h = harness(), saved = h.read(new URLSearchParams('q=rose'));
  assert.equal(saved.mode, 'hybrid');
  assert.equal(saved.author, '');
  assert.equal(saved.include_reference, false);
  assert.equal(saved.issues.length, 0);
});

test('unsupported enum values, malformed language and control characters produce explicit issues', () => {
  const h = harness();
  const saved = h.read(new URLSearchParams('q=rose&mode=arbitrary&order=reverse&lang=%3Cscript%3E&ref=true&author=Sappho%00'));
  assert.equal(saved.issues.length, 5);
  assert.equal(saved.mode, 'hybrid');
  assert.equal(saved.order, 'relevance');
  assert.equal(saved.author, '');
  assert.equal(saved.language, '');
});

test('missing saved author and edition stay as explicit unavailable options, never All', async () => {
  const h = harness();
  const saved = h.restore(new URLSearchParams('q=rose&author=Missing%20author&edition=Missing%20edition&lang=ell'));
  assert.equal(h.ui.authorFilter.value, 'Missing author');
  assert.equal(h.ui.edition.value, 'Missing edition');
  assert.equal(h.ui.language.value, 'ell');
  assert.match(h.ui.authorFilter.options.at(-1).textContent, /unavailable/);
  const promise = h.search(saved.query, saved.mode);
  assert.equal(h.pending[0].params.author, 'Missing author');
  assert.equal(h.pending[0].params.edition, 'Missing edition');
  h.pending[0].resolve({ results: [], total: 0 }); await promise;
  assert.match(h.ui.resultsList.textContent, /has not been broadened/);
});

test('inflight search persists its request snapshot rather than subsequently changed controls', async () => {
  const h = harness();
  h.ui.authorFilter.value = 'Ibycus'; h.ui.edition.value = 'Fixture edition';
  h.ui.language.value = 'grc'; h.ui.order.value = 'chronological'; h.ui.reference.checked = true;
  const promise = h.search('love like an old racehorse', 'themes');
  h.ui.authorFilter.value = 'Sappho'; h.ui.edition.value = '';
  h.ui.language.value = 'eng'; h.ui.order.value = 'relevance'; h.ui.reference.checked = false;
  // A concurrent passage navigation may have changed the id while search ran.
  h.location.href = 'https://example.test/?id=new-passage&campaign=keep';
  h.pending[0].resolve(response('fixture')); await promise;
  const url = new URL(h.location.href);
  assert.equal(url.searchParams.get('author'), 'Ibycus');
  assert.equal(url.searchParams.get('edition'), 'Fixture edition');
  assert.equal(url.searchParams.get('lang'), 'grc');
  assert.equal(url.searchParams.get('order'), 'chronological');
  assert.equal(url.searchParams.get('ref'), '1');
  assert.equal(url.searchParams.get('id'), 'new-passage');
  assert.match(h.ui.resultsSummary.textContent, /author chronology/);
});

test('search spinner follows current request completion, failure and invalidation', async () => {
  const h = harness();
  const first = h.search('first'), second = h.search('second');
  assert.equal(h.ui.resultsSummary.classList.contains('melos-loading'), true);
  h.pending[0].resolve(response('first')); await first;
  assert.equal(h.ui.resultsSummary.classList.contains('melos-loading'), true);
  h.pending[1].resolve({ results: [], total: 0 }); await second;
  assert.equal(h.ui.resultsSummary.classList.contains('melos-loading'), false);
  const failed = h.search('failure'); h.pending[2].reject(new Error('offline')); await failed;
  assert.equal(h.ui.resultsSummary.classList.contains('melos-loading'), false);
  const outdated = h.search('outdated');
  await h.search('x'.repeat(1001));
  assert.equal(h.ui.resultsSummary.classList.contains('melos-loading'), false);
  h.pending[3].resolve(response('old')); await outdated;
  assert.equal(h.ui.resultsSummary.classList.contains('melos-loading'), false);
});

test('old search responses cannot overwrite a newer filtered URL and pagination keeps its original filters', async () => {
  const h = harness();
  h.ui.authorFilter.value = 'Sappho'; const old = h.search('old', 'exact');
  h.ui.authorFilter.value = 'Ibycus'; const fresh = h.search('fresh', 'forms');
  h.pending[1].resolve(response('fresh')); await fresh;
  h.pending[0].resolve(response('old')); await old;
  assert.equal(new URL(h.location.href).searchParams.get('author'), 'Ibycus');
  assert.equal(new URL(h.location.href).searchParams.get('mode'), 'forms');
  h.ui.authorFilter.value = 'Sappho';
  const page = h.search('fresh', 'forms', true);
  assert.equal(h.pending[2].params.author, 'Ibycus');
  assert.equal(h.pending[2].params.offset, 1);
  h.pending[2].resolve(response('page2')); await page;
  assert.equal(new URL(h.location.href).searchParams.get('author'), 'Ibycus');
});

test('startup restores saved state only after asynchronous option populations and blocks invalid auto-search', () => {
  const init = script.slice(script.indexOf('  async function initialize('), script.indexOf('  ui.searchForm.addEventListener'));
  assert.ok(init.indexOf('restoreSearchUrl(params)') > init.indexOf('updateAuthorOptions()'));
  assert.ok(init.indexOf('restoreSearchUrl(params)') > init.indexOf('updateEditionOptions(works)'));
  assert.match(init, /if \(saved\.issues\.length\)/);
  assert.match(init, /else if \(saved\.query\) search\(saved\.query, saved\.mode\)/);
  assert.match(init, /if \(saved\.query \|\| saved\.issues\.length\) \{/);
  // A search link opens no passage: the reading desk says so instead of staying on its loading line.
  assert.match(init.slice(init.indexOf('if (saved.query || saved.issues.length) {')), /^[^}]*renderPassageEmpty\('Choose a search result[^}]*return;/);
});

test('search limit uses trimmed Unicode codepoints, never shortened request payloads', async () => {
  for (const character of ['x', '\u{1f600}']) {
    const h = harness(), query = character.repeat(1000);
    const valid = h.search(`  ${query}  `, 'exact');
    assert.equal(h.pending.length, 1);
    assert.equal(h.pending[0].params.q, query);
    h.pending[0].resolve(response('valid')); await valid;
    const url = h.location.href;
    await h.search(character.repeat(1001), 'themes');
    assert.equal(h.pending.length, 1);
    assert.equal(h.previews.length, 1);
    assert.equal(h.location.href, url);
    assert.equal(h.state.displayedSearch, null);
    assert.equal(h.ui.searchInput.value, character.repeat(1001));
    assert.match(h.ui.searchQueryError.textContent, /1,001/);
  }
});

test('oversize input is retained with inline accessible error, cancels stale rendering and recovers', async () => {
  const h = harness();
  h.ui.searchInput.setAttribute('aria-describedby', 'existing-help');
  const old = h.search('pending', 'exact');
  h.state.dictionarySequence = 10;
  h.ui.dictionaryPreview.append(new Element('p', '', 'old preview'));
  const query = '  ' + 'x'.repeat(1302) + '  ';
  await h.search(query, 'exact');
  assert.equal(h.ui.searchInput.value, query);
  assert.equal(h.pending.length, 1);
  assert.equal(h.previews.length, 1);
  assert.equal(h.state.dictionarySequence, 11);
  assert.equal(h.ui.dictionaryPreview.hidden, true);
  assert.equal(h.ui.dictionaryPreview.children.length, 0);
  assert.equal(h.ui.searchForm.afterElement, h.ui.searchQueryError);
  assert.equal(h.ui.searchQueryError.getAttribute('role'), 'alert');
  assert.equal(h.ui.searchQueryError.hidden, false);
  assert.match(h.ui.searchQueryError.textContent, /1,302.*full input is retained/);
  assert.equal(h.ui.searchInput.getAttribute('aria-invalid'), 'true');
  assert.equal(h.ui.searchInput.getAttribute('aria-describedby'), 'existing-help search-query-error');
  h.pending[0].resolve(response('outdated')); await old;
  assert.equal(h.visited.length, 0);
  assert.equal(h.ui.resultsList.children.length, 0);
  assert.equal(h.ui.resultsHeading.textContent, 'Query exceeds the search limit');
  const valid = h.search('recovered', 'exact');
  assert.equal(h.ui.searchQueryError.hidden, true);
  assert.equal(h.ui.searchInput.getAttribute('aria-invalid'), null);
  assert.equal(h.ui.searchInput.getAttribute('aria-describedby'), 'existing-help');
  h.pending[1].resolve(response('recovered')); await valid;
  assert.equal(h.state.displayedSearch.query, 'recovered');
  assert.equal(new URL(h.location.href).searchParams.get('q'), 'recovered');
});

test('saved query uses the same codepoint limit, retains oversize value, and still rejects controls', () => {
  const h = harness();
  const valid = '\u{1f600}'.repeat(1000);
  assert.equal(h.restore(new URLSearchParams({ q: `  ${valid}  ` })).issues.length, 0);
  const invalid = '\u{1f600}'.repeat(1001);
  const saved = h.restore(new URLSearchParams({ q: invalid }));
  assert.equal(saved.query, invalid);
  assert.equal(h.ui.searchInput.value, invalid);
  assert.match(saved.issues[0], /Saved query: Search accepts up to 1,000/);
  assert.equal(h.ui.searchQueryError.hidden, false);
  assert.equal(h.pending.length, 0);
  const controls = h.restore(new URLSearchParams({ q: 'x\u0000y' }));
  assert.equal(controls.query, '');
  assert.match(controls.issues[0], /invalid/);
  assert.equal(h.ui.searchQueryError.hidden, true);
});

test('oversize form and current usage query are gated before their downstream actions', () => {
  for (const key of ['usage', 'lookupForm']) {
    const h = harness(), calls = [];
    const start = script.indexOf(`  ui.${key}.addEventListener('click', () => {`);
    const end = script.indexOf('\n  });', start) + '\n  });'.length;
    h.ui[key] = { addEventListener(event, callback) { this.click = callback; } };
    Object.assign(h.context, { window: { MelosUsageSpace: { open: (...args) => calls.push(args) } },
      inspectWord: (...args) => calls.push(args), message: (...args) => calls.push(args) });
    h.ui.searchInput.value = 'x'.repeat(1302);
    vm.runInContext(script.slice(start, end), h.context);
    h.ui[key].click();
    assert.equal(calls.length, 0);
    assert.equal(h.pending.length, 0);
    assert.equal(h.ui.searchQueryError.hidden, false);
  }
});

test('inline limit notice is scoped and can wrap across the search area', () => {
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  assert.match(css, /\.reader-hero \.search-query-error\{max-width:55rem;margin:10px 0 0;overflow-wrap:anywhere\}/);
});

test('query trimming matches API whitespace rather than JS BOM trimming', async () => {
  const h = harness(), body = 'x'.repeat(1000);
  const valid = h.search(`\u0085${body}\u0085`, 'exact');
  assert.equal(h.pending[0].params.q, body);
  h.pending[0].resolve(response('valid')); await valid;
  await h.search(`\ufeff${body}`, 'exact');
  assert.equal(h.pending.length, 1);
  assert.equal(h.ui.searchInput.value, `\ufeff${body}`);
  assert.match(h.ui.searchQueryError.textContent, /1,001/);
  assert.equal(h.read(new URLSearchParams({ q: `\u0085${body}` })).issues.length, 0);
  assert.equal(h.read(new URLSearchParams({ q: `\ufeff${body}` })).issues.length, 1);
  assert.equal(vm.runInContext('trimSearchQuery("\\u001cx\\u001f")', h.context), 'x');
});

test('Forms relation and total gap round-trip and survive pagination and unsent changes', async () => {
  const h = harness(), saved = h.restore(new URLSearchParams('q=first+second&mode=forms&forms_relation=proximity&slop=3'));
  assert.equal(h.ui.formsRelation.value, 'proximity'); assert.equal(h.ui.formsSlop.value, '3');
  const first = h.search(saved.query, saved.mode);
  assert.equal(h.pending[0].params.forms_relation, 'proximity'); assert.equal(h.pending[0].params.slop, 3);
  h.ui.formsRelation.value = 'all_terms'; h.ui.formsSlop.value = '49';
  h.pending[0].resolve(response('first')); await first;
  assert.equal(new URL(h.location.href).searchParams.get('forms_relation'), 'proximity');
  assert.equal(new URL(h.location.href).searchParams.get('slop'), '3');
  const page = h.search(saved.query, saved.mode, true);
  assert.equal(h.pending[1].params.forms_relation, 'proximity'); assert.equal(h.pending[1].params.slop, 3);
  h.pending[1].resolve(response('second')); await page;
  const scope = vm.runInContext('usageSnapshot("edited query")', h.context);
  assert.equal(scope.forms_relation, 'proximity'); assert.equal(scope.slop, 3);
  assert.match(scope.scope_notice, /Current inputs differ/);
});

test('Forms defaults preserve single-word lookup and all-terms requests send zero gap without a phrase claim', async () => {
  const h = harness();
  assert.equal(h.read(new URLSearchParams('q=word&mode=forms')).forms_relation, 'ordered');
  const first = h.search('word', 'forms');
  assert.equal(h.pending[0].params.forms_relation, 'ordered'); assert.equal(h.pending[0].params.slop, 0);
  h.pending[0].resolve(response('single')); await first;
  h.ui.formsRelation.value = 'all_terms'; h.ui.formsSlop.value = '9';
  const next = h.search('first second', 'forms');
  assert.equal(h.pending[1].params.slop, 0);
  h.pending[1].resolve({ ...response('both'), search_contract: { relation: 'all_terms', query_term_count: 2, slop: 0, complete: true } }); await next;
  assert.match(h.ui.resultsSummary.textContent, /not a phrase match/);
  const url = h.write(h.location.href, { query: 'word', mode: 'exact' });
  assert.equal(url.searchParams.has('forms_relation'), false); assert.equal(url.searchParams.has('slop'), false);
});

test('invalid saved Forms settings block reload instead of silently broadening the search', () => {
  const h = harness();
  for (const value of ['-1', '51', '1.5', 'NaN', '1e1', '', '  ']) {
    const saved = h.read(new URLSearchParams({ q: 'first second', mode: 'forms', slop: value }));
    assert.ok(saved.issues.length, value);
  }
  assert.match(h.read(new URLSearchParams('forms_relation=unsupported')).issues[0], /unsupported/);
  assert.match(h.read(new URLSearchParams('forms_relation=all_terms&slop=4')).issues[0], /no gap allowance/);
  for (const value of ['0', '50']) assert.equal(h.read(new URLSearchParams({ slop: value })).issues.length, 0);
});

test('Forms controls are mode-specific, all-terms hides gap, invalid gap sends no request', async () => {
  const h = harness(), update = vm.runInContext('updateFormsControls', h.context);
  update(); assert.equal(h.ui.formsOptions.hidden, true);
  h.restore(new URLSearchParams('mode=forms&forms_relation=all_terms'));
  update(); assert.equal(h.ui.formsOptions.hidden, false);
  assert.equal(h.ui.formsSlopLabel.hidden, true); assert.equal(h.ui.formsSlop.disabled, true);
  assert.match(h.ui.formsNote.textContent, /not a phrase match/);
  h.ui.formsRelation.value = 'proximity'; update();
  assert.equal(h.ui.formsSlopLabel.hidden, false); assert.equal(h.ui.formsSlop.disabled, false);
  assert.match(h.ui.formsNote.textContent, /total extra words/);
  h.ui.formsSlop.value = '3.5'; await h.search('first second', 'forms');
  assert.equal(h.pending.length, 0);
  assert.equal(h.ui.resultsHeading.textContent, 'Check Forms search controls');
  assert.equal(h.ui.formsSlop.getAttribute('aria-invalid'), 'true');
  assert.equal(h.ui.searchInput.getAttribute('aria-invalid'), null);
});

test('partial Forms response counts are expressly incomplete, never a corpus-wide absence claim', async () => {
  const h = harness(), first = h.search('first second', 'forms');
  h.pending[0].resolve({ results: [], total: 0, search_contract: { relation: 'ordered', query_term_count: 2, complete: false } });
  await first;
  assert.match(h.ui.resultsSummary.textContent, /in this incomplete search/);
  assert.match(h.ui.resultsList.textContent, /does not establish absence from the indexed corpus/);
});

test('selected Related word forms explicitly resets order and gap before search', () => {
  const start = script.indexOf("  for (const button of ui.selectionActions.querySelectorAll('[data-phrase-mode]')) button.addEventListener('click'");
  const selection = script.slice(start, script.indexOf("  document.addEventListener('selectionchange'", start));
  const h = harness(); let click;
  const button = { dataset: { phraseMode: 'forms' }, addEventListener(event, handler) { click = handler; } };
  h.ui.selectionActions = { querySelectorAll: () => [button] };
  h.state.passage = { id: 'fixture' }; h.state.selectedText = 'first second';
  h.ui.formsRelation.value = 'all_terms'; h.ui.formsSlop.value = '9';
  const calls = []; h.context.search = (...args) => calls.push(args);
  vm.runInContext(selection, h.context); click();
  assert.equal(h.ui.formsRelation.value, 'ordered'); assert.equal(h.ui.formsSlop.value, '0');
  assert.equal(h.mode(), 'forms'); assert.equal(calls[0][0], 'first second');
});

test('usage click rejects invalid current Forms input before numeric coercion', () => {
  for (const raw of ['', '1e1', '3.5', '51', 'invalid']) {
    const h = harness(), calls = [];
    h.restore(new URLSearchParams('q=first+second&mode=forms'));
    h.ui.formsSlop.value = raw;
    h.ui.usage = { addEventListener(event, callback) { this.click = callback; } };
    h.context.window = { MelosUsageSpace: { open: (...args) => calls.push(args) } };
    const start = script.indexOf("  ui.usage.addEventListener('click', () => {");
    vm.runInContext(script.slice(start, script.indexOf('\n  });', start) + '\n  });'.length), h.context);
    h.ui.usage.click();
    assert.equal(calls.length, 0, raw);
    assert.match(h.ui.resultsSummary.textContent, /whole number from 0 to 50/);
    assert.equal(h.ui.formsSlop.value, raw);
    assert.equal(h.ui.formsSlop.getAttribute('aria-invalid'), 'true');
  }
});

test('usage retains a valid displayed Forms snapshot but explicitly reports invalid unsent controls', async () => {
  const h = harness(), calls = [];
  h.restore(new URLSearchParams('q=first+second&mode=forms&slop=0'));
  const search = h.search('first second', 'forms'); h.pending[0].resolve(response('valid')); await search;
  h.ui.usage = { addEventListener(event, callback) { this.click = callback; } };
  h.context.window = { MelosUsageSpace: { open: (...args) => calls.push(args) } };
  const start = script.indexOf("  ui.usage.addEventListener('click', () => {");
  vm.runInContext(script.slice(start, script.indexOf('\n  });', start) + '\n  });'.length), h.context);
  for (const raw of ['', '1e1', 'invalid']) {
    h.ui.formsSlop.value = raw; h.ui.usage.click();
    const [query, , scope] = calls.at(-1);
    assert.equal(query, 'first second'); assert.equal(scope.forms_relation, 'ordered'); assert.equal(scope.slop, 0);
    assert.match(scope.scope_notice, /controls are invalid.*last successfully displayed/);
    assert.equal(h.state.displayedSearch.slop, 0);
  }
  assert.equal(calls.length, 3);
});
