import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const context = vm.createContext({ window: {}, AbortController });
vm.runInContext(readFileSync(new URL('../js/passage-analysis.js', import.meta.url), 'utf8'), context);
const render = context.window.MelosPassageAnalysis.renderPublishedCommentary;
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [] }); }
  append(...children) { this.children.push(...children); }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const node = (...args) => new Element(...args);
// Synthetic source strings test safe rendering, not a scholarly interpretation.
const fixture = () => ({ passage: { id: 'synthetic:poem' }, published_commentary: {
  status: 'available', evidence_type: 'published_commentary', scope: 'whole_poem_commentary',
  selection_aligned: false, word_attestation: false, line_attestation: false,
  parent_id: 'synthetic:poem', commentary_id: 'synthetic:poem:commentary', source_title: 'Synthetic printed edition',
  source_pdf_sha256: 'a'.repeat(64), paragraph_count: 2,
  paragraphs: [{ ordinal: 0, citation: 'Printed p. 3', text: 'Full source paragraph. '.repeat(100) },
    { ordinal: 1, citation: 'Printed p. 4', text: 'Uncertain source �', uncertain_ocr: true }] } });
test('full whole-poem commentary stays collapsed, source-labelled, and separate from word meaning', () => {
  const data = fixture(), host = node('div'); assert.equal(render(host, data, node), true);
  const panel = host.children[0]; assert.equal(panel.tag, 'details'); assert.equal(panel.open, undefined);
  assert.match(panel.textContent, /Whole-poem commentary, not a translation, grammatical parse/);
  for (const paragraph of data.published_commentary.paragraphs) assert.ok(panel.textContent.includes(paragraph.text));
  assert.match(panel.textContent, /Printed p\. 3/); assert.match(panel.textContent, /OCR is uncertain/);
});
test('wrong parent, changed scope, malformed source, and missing paragraphs fail closed', () => {
  for (const change of [source => { source.parent_id = 'other'; }, source => { source.commentary_id = 'other:commentary'; },
    source => { source.scope = 'word_annotation'; }, source => { source.word_attestation = true; },
    source => { source.line_attestation = true; }, source => { source.selection_aligned = true; },
    source => { source.source_pdf_sha256 = ''; }, source => { source.paragraph_count = 9; },
    source => { source.paragraphs[0].text = null; }]) {
    const data = fixture(), host = node('div'); change(data.published_commentary);
    assert.equal(render(host, data, node), false); assert.equal(host.children.length, 0);
  }
});
test('HTML-looking source prose remains literal and no unrelated edition hyperlink is created', () => {
  const data = fixture(), host = node('div');
  data.published_commentary.source_title = '<img src=x onerror=alert(1)>';
  data.published_commentary.paragraphs[0].text = '<script>unsafe()</script>';
  data.published_commentary.paragraphs[0].citation = '<a href="javascript:bad">source</a>';
  data.published_commentary.source_url = 'https://wrong-edition.test/';
  assert.equal(render(host, data, node), true);
  const flatten = element => [element, ...element.children.flatMap(flatten)];
  assert.equal(flatten(host).some(element => ['a', 'img', 'script'].includes(element.tag)), false);
  assert.ok(host.textContent.includes('<script>unsafe()</script>'));
});
test('absent commentary from older backend snapshots leaves existing analysis untouched', () => {
  const host = node('div'); host.append(node('p', '', 'Existing result'));
  assert.equal(render(host, { passage: { id: 'p' } }, node), false);
  assert.equal(host.textContent, 'Existing result');
});
test('actual analyze-passage context envelope renders the source and explicit context absence does not fall back', () => {
  const data = fixture(), source = data.published_commentary;
  delete data.published_commentary; data.context = { published_commentary: source };
  const host = node('div'); assert.equal(render(host, data, node), true);
  assert.ok(host.textContent.includes(source.paragraphs[0].text));
  data.published_commentary = source; data.context.published_commentary = null;
  assert.equal(render(node('div'), data, node), false);
});
test('authoritative source PDF metadata mismatch fails closed when supplied', () => {
  const data = fixture(); data.passage.metadata = { source_pdf_sha256: 'b'.repeat(64) };
  assert.equal(render(node('div'), data, node), false);
});
