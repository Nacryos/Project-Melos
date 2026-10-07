import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../js/lexicon-page.js', import.meta.url), 'utf8');
const context = vm.createContext({ window: {}, URL, URLSearchParams });
vm.runInContext(source, context);
const { sourceUrl, readState, writeState, readerUrl, splitCandidates } = context.window.MelosLexiconPage;

test('restores bounded URL state and rejects unsupported modes, letters and offsets', () => {
  const state = readState('https://melos.test/lexicon?q=logos&lemma=λόγος&prefix=λ&mode=greek&offset=30&author=Sappho');
  assert.equal(state.lemma, 'λόγος'); assert.equal(state.prefix, 'λ'); assert.equal(state.offset, 30); assert.equal(state.author, 'Sappho');
  const invalid = readState('https://melos.test/lexicon?mode=evil&prefix=script&offset=-2');
  assert.equal(invalid.mode, 'auto'); assert.equal(invalid.offset, 0); assert.equal(invalid.prefix, '');
  assert.equal(readState('https://melos.test/lexicon?offset=Infinity').offset, 0);
  assert.equal(readState(`https://melos.test/lexicon?q=${'x'.repeat(160)}&lemma=${'x'.repeat(160)}`).q.length, 100);
  assert.equal(readState(`https://melos.test/lexicon?lemma=${'x'.repeat(160)}`).lemma.length, 100);
});

test('URL state preserves unrelated parameters and safely roundtrips query and selected lemma', () => {
  const state = { q: 'love & longing', lemma: 'ἔρως', prefix: '', mode: 'english', offset: 30, author: 'Author & Other' };
  const url = writeState('https://melos.test/lexicon?keep=yes&prefix=α', state);
  assert.equal(url.searchParams.get('keep'), 'yes'); assert.equal(url.searchParams.has('prefix'), false);
  assert.equal(readState(url.href).q, state.q); assert.equal(readState(url.href).lemma, state.lemma);
});

test('reader links preserve query, mode and author without accepting a redirect', () => {
  const url = new URL(readerUrl('λόγος & <text>', 'forms', 'Sappho & Alcaeus'), 'https://melos.test');
  assert.equal(url.pathname, '/'); assert.equal(url.searchParams.get('q'), 'λόγος & <text>');
  assert.equal(url.searchParams.get('mode'), 'forms'); assert.equal(url.searchParams.get('author'), 'Sappho & Alcaeus');
});

test('source URLs reject scripts, credentials and local paths', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,hi', '//example.org', '/api/secrets', 'https://name:pass@example.org']) assert.equal(sourceUrl(value), '');
  assert.equal(sourceUrl('https://example.org/dictionary?id=1'), 'https://example.org/dictionary?id=1');
});

test('exact source candidates remain separate from nearby and quarantined analyses', () => {
  const fixture = { candidates: [
    { lemma: 'fixture-a', edit_distance: 0, match_kind: 'indexed_form', analysis: 'one' },
    { lemma: 'fixture-a', edit_distance: 0, match_kind: 'indexed_form', analysis: 'two' },
    { lemma: 'fixture-b', edit_distance: 1, match_kind: 'indexed_form' },
    { lemma: 'fixture-c', edit_distance: 0, match_kind: 'indexed_form', quarantined: true },
    { lemma: 'fixture-d', edit_distance: 0, match_kind: 'indexed_form', assertion_type: 'model_inference' },
  ] };
  const result = splitCandidates(fixture);
  assert.equal(result.exact.length, 2); assert.equal(result.nearby.length, 1);
  assert.equal(result.exact[1].analysis, 'two');
});

test('page uses safe DOM rendering and source preview projection', () => {
  assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/);
  assert.match(source, /preview\?\.buildPreview\(data\)/);
  assert.match(source, /sequence !== browseSequence/); assert.match(source, /sequence !== entrySequence/);
  assert.match(source, /AbortController/);
});

// Minimal DOM with deliberately non-cancellable fetches: stale responses must
// be rejected by request identity even if the transport ignores AbortSignal.
function mount() {
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.events = {}; this.value = ''; this.textContent = ''; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; this.textContent = ''; }
    setAttribute(key, value) { this.attributes[key] = value; }
    removeAttribute(key) { delete this.attributes[key]; }
    addEventListener(key, fn) { this.events[key] = fn; }
    querySelectorAll(tag) { return this.children.flatMap(child => [ ...(child.tag === tag ? [child] : []), ...child.querySelectorAll(tag)]); }
    get childNodes() { return this.children; }
  }
  const html = readFileSync(new URL('../lexicon.html', import.meta.url), 'utf8');
  const elements = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element('div')]));
  const requests = [];
  const location = { href: 'https://melos.test/lexicon' };
  const document = { getElementById: id => elements[id], createElement: tag => new Element(tag),
    createElementNS: (_, tag) => new Element(tag), querySelectorAll: () => [] };
  const window = { matchMedia: () => ({ matches: false }), addEventListener() {},
    melosApiFetch: (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve: data => resolve({ ok: true, json: async () => data }), reject })) };
  const browser = vm.createContext({ window, document, location, history: { replaceState: (_, __, url) => { location.href = String(url); }, pushState: (_, __, url) => { location.href = String(url); } }, URL, URLSearchParams, AbortController, setTimeout, clearTimeout });
  vm.runInContext(readFileSync(new URL('../js/dictionary-preview.js', import.meta.url), 'utf8'), browser);
  vm.runInContext(source, browser);
  const bodyText = element => [element.textContent, ...element.children.map(bodyText)].join(' ');
  return { elements, requests, bodyText };
}
const settle = async () => { for (let index = 0; index < 10; index++) await Promise.resolve(); };

test('custom SVG arrows retain textual navigation labels without arrow glyphs', () => {
  const html = readFileSync(new URL('../lexicon.html', import.meta.url), 'utf8');
  assert.doesNotMatch(source + html, /[←→↗]/u);
  assert.match(source, /document\.createElementNS\(namespace, 'svg'\)/);
  assert.match(source, /'aria-hidden': 'true'/);
  assert.match(html, /Return to the reader <span data-lexicon-arrow="right"/);
});

test('markup and programmatic submissions both respect the API 100-character limit', () => {
  const html = readFileSync(new URL('../lexicon.html', import.meta.url), 'utf8');
  assert.match(html, /id="lexicon-query"[^>]*maxlength="100"/);
  const { elements, requests } = mount();
  elements['lexicon-query'].value = 'x'.repeat(160);
  elements['lexicon-mode'].value = 'english';
  elements['lexicon-search'].events.submit({ preventDefault() {} });
  const last = requests.filter(row => row.url.startsWith('/api/lexicon?')).at(-1);
  assert.equal(new URL(last.url, 'https://melos.test').searchParams.get('q').length, 100);
  assert.equal(elements['lexicon-query'].value.length, 100);
});

test('actual endpoint response shape retains source entries, homographs and bounded-search warnings', async () => {
  // Synthetic content following backend.discovery._display_entry and lexicon;
  // these assertions exercise the browser using the complete API field shape.
  const { elements, requests, bodyText } = mount();
  const results = [1, 2].map(number => ({ id: `test:a${number}`, headword: 'ἄλφα', lemma: 'ἄλφα',
    source: 'Synthetic dictionary', source_url: 'https://example.org/test-only', license: 'Test only',
    meaning: `Synthetic meaning ${number}`, meanings: [{ id: `test:a${number}:sense`, text: `Synthetic meaning ${number}`,
      source: 'Synthetic dictionary', source_url: 'https://example.org/test-only', lexicon_entry_id: `test:a${number}`,
      source_locator: null, sense_path: null }], meaning_count: 1, entry_count: 1, homograph: String(number), meaning_status: 'source_structured' }));
  requests.find(row => row.url.startsWith('/api/lexicon?')).resolve({ results, total: 2, limit: 30, offset: 0, has_more: false,
    mode: 'english', method: 'Alphabetical source headwords; English meanings are verified structured dictionary spans.',
    warnings: ['Synthetic bounded search: the count covers only the inspected window.'],
    search_contract: { complete: false, english_candidate_limit: 250, candidates_checked: 250,
      ordering: 'diacritic-folded Greek headword, exact headword, source entry id', sense_selection: 'source order, not contextual interpretation' } });
  await settle();
  const buttons = elements['headword-list'].querySelectorAll('button');
  assert.equal(buttons.length, 2); assert.notEqual(buttons[0].dataset.entry, buttons[1].dataset.entry);
  assert.match(bodyText(elements['headword-list']), /Synthetic meaning 1/);
  assert.match(bodyText(elements['headword-list']), /Synthetic meaning 2/);
  assert.match(bodyText(elements['headword-list']), /Synthetic dictionary/);
  assert.match(elements['browse-note'].textContent, /inspected window/);
  assert.equal(elements['headword-next'].disabled, true);
});

test('a linked full source entry stays accessible when no safe short definition exists', async () => {
  const { elements, requests, bodyText } = mount();
  requests.find(row => row.url.startsWith('/api/lexicon?')).resolve({ results: [{ id: 'test:a', headword: 'Fixture' }], total: 1 });
  await settle();
  requests.find(row => row.url.startsWith('/api/word?')).resolve({ form: 'Fixture', candidates: [
    { lemma: 'Fixture', edit_distance: 0, match_kind: 'lexicon_headword', lexicon_entry_ids: ['test:a'], source_url: 'https://example.org/test-only' }],
    lexicon_entries: [{ id: 'test:a', lemma: 'Fixture', source: 'Synthetic dictionary', source_url: 'https://example.org/test-only',
      rendered_entry_text: 'Synthetic full source text', dictionary_senses: [], dictionary_senses_status: 'no_safe_definition_spans' }] });
  await settle();
  assert.match(bodyText(elements['entry-body']), /No verified short meaning is available/);
  assert.match(bodyText(elements['entry-body']), /Synthetic full source text/);
  assert.match(bodyText(elements['entry-body']), /Read full source entry/);
});

test('late dictionary response cannot replace a newly selected headword', async () => {
  const { elements, requests, bodyText } = mount();
  requests.find(row => row.url.startsWith('/api/lexicon?')).resolve({ results: [
    { id: 'synthetic-a', headword: 'Fixture A' }, { id: 'synthetic-b', headword: 'Fixture B' }
  ], total: 2 });
  await settle();
  const first = requests.find(row => row.url.includes('form=Fixture+A'));
  elements['headword-list'].querySelectorAll('button')[1].events.click();
  const second = requests.find(row => row.url.includes('form=Fixture+B'));
  assert.equal(first.options.signal.aborted, true);
  second.resolve({ form: 'Fixture B', candidates: [{ lemma: 'Fixture B', edit_distance: 0, match_kind: 'indexed_form', analysis_text: 'Second source analysis' }] });
  await settle();
  first.resolve({ form: 'Fixture A', candidates: [{ lemma: 'Fixture A', edit_distance: 0, match_kind: 'indexed_form', analysis_text: 'Stale first analysis' }] });
  await settle();
  assert.equal(elements['entry-heading'].textContent, 'Fixture B');
  assert.match(bodyText(elements['entry-body']), /Second source analysis/);
  assert.doesNotMatch(bodyText(elements['entry-body']), /Stale first analysis/);
});

test('late browser response cannot overwrite a new alphabet selection', async () => {
  const { elements, requests } = mount();
  const first = requests.find(row => row.url.startsWith('/api/lexicon?'));
  elements['lexicon-alphabet'].querySelectorAll('button')[2].events.click();
  const second = requests.filter(row => row.url.startsWith('/api/lexicon?'))[1];
  second.resolve({ results: [], total: 0 }); await settle();
  first.resolve({ results: [{ id: 'synthetic-old', headword: 'Stale result' }], total: 1 }); await settle();
  assert.equal(elements['headword-list'].querySelectorAll('button').length, 0);
  assert.match(elements['browse-status'].textContent, /No matching headwords/);
  assert.equal(first.options.signal.aborted, true);
});
