import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic display mechanics only; these fixtures are not literary evidence.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [], handlers: {} }); }
  append(...children) { this.children.push(...children); }
  addEventListener(event, callback) { this.handlers[event] = callback; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const descendants = root => root.children.flatMap(child => [child, ...descendants(child)]);
const opened = [];
const context = vm.createContext({ node: (tag, cls, text) => new Element(tag, cls, text),
  chronologyClaim: () => null, qualityLabel: value => value, passageTranslationPreviews: () => [],
  openPassage: id => opened.push(id), safeLink(url, label) {
    try { const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol)) return null;
      const link = new Element('a', '', label); link.href = parsed.href; return link; } catch { return null; }
  } });
vm.runInContext(script.slice(script.indexOf('  function renderResult('), script.indexOf('  function renderDictionaryPreview(')), context);
const render = vm.runInContext('renderResult', context), proof = vm.runInContext('sequenceMatchProof', context);
const contract = row => ({ version: 1, scope: 'single_stored_passage', offset_basis: 'Unicode codepoints in original passage.text',
  relation: row.sequence_match.relation, slop: row.sequence_match.slop, query_term_count: row.sequence_match.terms.length });
function record() {
  return { id: 'fixture', text: 'alpha gap beta', source_url: 'https://example.test/passage',
    sequence_match: { relation: 'ordered', slop: 1, extra_words: 1, terms: [
      { query_index: 0, query_term: 'alpha', matched_form: 'alpha', token_index: 0,
        source_spans: [{ start: 0, end: 5, text: 'alpha' }], expansion_refs: [{ kind: 'literal_query' }] },
      { query_index: 1, query_term: 'beta', matched_form: 'beta', token_index: 2,
        source_spans: [{ start: 10, end: 14, text: 'beta' }], expansion_refs: [{ kind: 'dictionary_listed_form',
          source: 'Fixture dictionary', claim_id: 'fixture:claim', lemma: 'fixture lemma', source_url: 'https://example.test/form' }] }
    ] } };
}

test('sequence result retains passage preview and puts literal matched proof outside the opening button', () => {
  const row = record(), before = structuredClone(row), card = render(row, contract(row));
  const button = card.children[0], details = card.children[1];
  assert.equal(button.tag, 'button'); assert.equal(details.tag, 'details');
  assert.match(button.textContent, /alpha gap beta/);
  assert.match(button.textContent, /All 2 words · in order · 1 extra word/);
  assert.equal(descendants(button).some(child => ['a', 'button', 'summary', 'details'].includes(child.tag)), false);
  assert.equal(details.children[0].textContent, 'Matched words');
  assert.match(details.textContent, /Query word 2: beta · source word position 3/);
  assert.match(details.textContent, /Fixture dictionary/);
  assert.match(details.textContent, /fixture:claim/);
  assert.equal(descendants(details).filter(child => child.tag === 'a').length, 2);
  button.handlers.click(); assert.equal(opened.at(-1), row.id);
  assert.deepEqual(row, before);
});

test('all-terms proof makes no adjacency or gap assertion', () => {
  const row = record(); row.sequence_match.relation = 'all_terms'; row.sequence_match.extra_words = null; row.sequence_match.slop = 0;
  const result = proof(row, contract(row));
  assert.equal(result.label, 'All 2 words · anywhere in passage');
  assert.match(result.details.textContent, /not a phrase match/);
  assert.doesNotMatch(result.label, /extra word|nearby|in order/);
});

test('bounded provenance is disclosed without implying that query alternatives were omitted', () => {
  const row = record(); row.sequence_match.terms[1].expansion_refs_complete = false;
  const result = proof(row, contract(row));
  assert.match(result.details.textContent, /Some source references shown\./);
  assert.doesNotMatch(result.label, /incomplete|partial/);
  assert.match(result.label, /All 2 words/);
});

test('disjoint printed segments and supplementary Unicode offsets remain separate and literal', () => {
  const row = record(); row.text = '😀al-\npha beta';
  Object.assign(row.sequence_match.terms[0], { source_spans: [{ start: 1, end: 3, text: 'al' }, { start: 5, end: 8, text: 'pha' }] });
  Object.assign(row.sequence_match.terms[1], { source_spans: [{ start: 9, end: 13, text: 'beta' }] });
  const result = proof(row, contract(row)), segments = descendants(result.details).filter(child => child.cls === 'forms-proof-segment');
  assert.deepEqual(segments.map(child => child.textContent), ['al', 'pha', 'beta']);
  assert.match(result.details.textContent, /not a reconstructed quotation/);
  assert.match(result.details.textContent, /not verse or manuscript line numbers/);
});

test('missing or inconsistent source spans, reused tokens and incomplete query positions do not get proof labels', () => {
  for (const mutate of [
    row => { row.sequence_match.terms[0].source_spans[0].text = 'invented'; },
    row => { row.sequence_match.terms[0].source_spans[0].end = 100; },
    row => { row.sequence_match.terms[0].source_spans = []; },
    row => { row.sequence_match.terms[1].query_index = 3; },
    row => { row.sequence_match.terms[1].token_index = 0; },
    row => { row.sequence_match.relation = 'unrecognized'; }
  ]) { const row = record(); mutate(row); assert.equal(proof(row, contract(row)), null); }
  assert.equal(proof(record(), { ...contract(record()), query_term_count: 3 }), null);
  assert.equal(proof(record(), { ...contract(record()), relation: 'proximity' }), null);
  assert.equal(proof(record(), { ...contract(record()), slop: 2 }), null);
});

test('literal markup is not executed and unsafe form-source links are omitted', () => {
  const row = record(); row.text = '<b> beta';
  row.sequence_match.terms[0].source_spans = [{ start: 0, end: 3, text: '<b>' }];
  row.sequence_match.terms[1].source_spans = [{ start: 4, end: 8, text: 'beta' }];
  row.sequence_match.terms[1].expansion_refs[0].source_url = 'javascript:unsafe()';
  const result = proof(row, contract(row));
  assert.match(result.details.textContent, /<b>/);
  assert.equal(descendants(result.details).filter(child => child.tag === 'b').length, 0);
  assert.equal(descendants(result.details).filter(child => child.tag === 'a').length, 1);
});

test('controls are labelled, hidden initially, bounded and use the established theme', () => {
  const html = readFileSync(new URL('../reader.html', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  assert.match(html, /id="forms-options" hidden/);
  assert.match(html, /for="forms-relation"/); assert.match(html, /for="forms-slop"/);
  for (const label of ['In this order', 'Nearby, any order', 'All words in passage', 'Extra words allowed']) assert.ok(html.includes(label));
  assert.match(html, /id="forms-slop" type="number" min="0" max="50" step="1" value="0"/);
  assert.match(css, /\.reader-hero \.forms-options\{[^}]*flex-wrap:wrap/);
  assert.match(css, /\.reader-hero \.forms-options\[hidden\][^{]*\{display:none\}/);
  assert.match(css, /\.reader-hero \.forms-options :focus-visible\{outline:2px solid var\(--on-dark\)/);
  assert.match(css, /@media\(max-width:820px\),\(max-height:600px\)/);
  assert.match(css, /\.reader-hero:has\(\.forms-options:not\(\[hidden\]\)\)\{[^}]*grid-template-rows:auto auto[^}]*row-gap:20px/);
  assert.match(css, /\.reader-hero:has\(\.forms-options:not\(\[hidden\]\)\) \.hero-copy\{position:relative[^}]*inset:auto/);
});

test('verified-word labels require an explicit source-offset contract and internally consistent position evidence', () => {
  assert.equal(proof(record()), null);
  for (const override of [{ version: 2 }, { scope: 'unknown' }, { offset_basis: 'UTF16' }, { slop: -1 }]) {
    assert.equal(proof(record(), { ...contract(record()), ...override }), null);
  }
  for (const mutate of [
    row => { row.sequence_match.terms[0].token_index = 3; },
    row => { row.sequence_match.slop = 0; },
    row => { row.sequence_match.extra_words = 2; },
    row => { row.sequence_match.terms[1].source_spans = [{ start: 1, end: 5, text: 'lpha' }]; },
    row => { row.sequence_match.relation = 'all_terms'; row.sequence_match.extra_words = null; }
  ]) { const row = record(); mutate(row); assert.equal(proof(row, contract(row)), null); }
});
