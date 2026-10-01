import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic display fixtures only; no dictionary/source records are authored.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [] }); }
  append(...children) { this.children.push(...children); }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const context = vm.createContext({
  node: (tag, cls, text) => new Element(tag, cls, text),
  addInspectorSection(title, host) { const section = new Element('section', '', title); host.append(section); return section; },
  safeLink(url, text) { return url?.startsWith('https://') ? new Element('a', '', text) : null; }
});
vm.runInContext(script.slice(script.indexOf('  function renderLexicalEvidence('), script.indexOf('  async function inspectWord(')), context);
const render = vm.runInContext('renderLexicalEvidence', context);
const hit = { scope: 'dictionary_quotation_not_morphological_parse', passage_id: 'fixture', lemma: 'Fixture entry',
  quote: '<literal source quotation>', citation: 'Printed reference', source_gloss: 'Literal fixture gloss',
  entry_id: 'entry-1', sense_id: 'sense-1', source: 'Fixture source', source_url: 'https://example.org/source', raw_sha256: 'fixture-hash' };
test('matching lexical quotation displays source excerpt, citation and provenance without a parse claim', () => {
  const host = new Element('div');
  assert.equal(render(host, { hits: [hit], coverage: 'Bounded source preview' }, 'fixture'), true);
  assert.match(host.textContent, /<literal source quotation>/);
  assert.match(host.textContent, /Literal fixture gloss/);
  assert.match(host.textContent, /Printed reference/);
  assert.match(host.textContent, /does not identify every quoted word/);
  const card = host.children[0].children.find(child => child.cls === 'candidate');
  assert.ok(card.children.some(child => child.tag === 'blockquote'));
  assert.ok(card.children.some(child => child.tag === 'details'));
});
test('a different passage, unsupported scope, or absent quotation does not create evidence', () => {
  for (const value of [{ ...hit, passage_id: 'other' }, { ...hit, scope: 'model_inference' }, { ...hit, quote: '' }]) {
    const host = new Element('div');
    assert.equal(render(host, { hits: [value] }, 'fixture'), false);
    assert.equal(host.children.length, 0);
  }
  assert.equal(render(new Element('div'), { hits: [hit] }, ''), false);
});
test('missing local sense remains missing and bounded coverage stays explicit', () => {
  const host = new Element('div');
  render(host, { hits: [{ ...hit, source_gloss: null }], entries_truncated: true }, 'fixture');
  assert.ok(!host.textContent.includes('Source sense excerpt'));
  assert.match(host.textContent, /additional entries or quotations were not checked/);
});
test('source decoding and OCR qualifications remain visible', () => {
  const host = new Element('div');
  render(host, { hits: [{ ...hit, raw_quote: 'fixture encoding', raw_quote_encoding: 'Source entities decoded', passage_quality: 'machine_corrected_ocr' }],
    warnings: ['Corrected OCR remains uncertain.'] }, 'fixture');
  assert.match(host.textContent, /Source entities decoded: fixture encoding/);
  assert.match(host.textContent, /Passage quality: machine_corrected_ocr/);
  assert.match(host.textContent, /Corrected OCR remains uncertain/);
});
