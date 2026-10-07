import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [] }); }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { (this.attributes ||= {})[name] = value; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
const scope = vm.createContext({ node: (...args) => new Element(...args) });
vm.runInContext(source.slice(source.indexOf('  function exactCommentaryNotes('), source.indexOf('  async function inspectWord(')), scope);
const find = scope.exactCommentaryNotes, render = scope.renderExactCommentaryNotes;
// Synthetic strings test source-scoped retrieval only, not literary claims.
const fixture = () => ({ id: 'synthetic:326', metadata: { source_pdf_sha256: 'a'.repeat(64) }, published_commentary: {
  status: 'available', evidence_type: 'published_commentary', scope: 'whole_poem_commentary',
  selection_aligned: false, word_attestation: false, line_attestation: false,
  parent_id: 'synthetic:326', commentary_id: 'synthetic:326:commentary', source_title: 'Synthetic edition', source_pdf_sha256: 'a'.repeat(64),
  paragraph_count: 2, paragraphs: [{ lemma: 'ά', scope: 'whole_poem_commentary', citation: 'Synthetic p. 3', text: 'First interpretation, and a deliberate second possibility.', uncertain_ocr: false },
    { lemma: 'β γ', scope: 'whole_poem_commentary', text: 'A phrase note, not about either individual word.' }] } });
test('identical NFC heading retrieves full note and citation without resolving its ambiguity', () => {
  const passage = fixture(), host = new Element('div');
  assert.equal(render(host, passage, 'α\u0301'), true);
  assert.ok(host.textContent.includes(passage.published_commentary.paragraphs[0].text));
  assert.match(host.textContent, /Synthetic p\. 3/); assert.match(host.textContent, /Note headed ά/);
  assert.match(host.textContent, /not a verified word alignment or a selected dictionary sense/);
  const greekHeading = host.children[0].children[0].children[0].children[0];
  assert.equal(greekHeading.text, 'ά');
  assert.match(greekHeading.attributes.style, /text-transform:none/);
});
test('accent removal, substring, and lemma inference do not retrieve source notes', () => {
  const passage = fixture();
  for (const query of ['α', 'β', 'γ', ' ά', 'άς']) assert.equal(find(passage, query).length, 0);
});
test('other poem commentary and different source PDF cannot contaminate this word', () => {
  for (const change of [p => { p.published_commentary.parent_id = 'synthetic:130b'; },
    p => { p.published_commentary.commentary_id = 'synthetic:130b:commentary'; },
    p => { p.published_commentary.source_pdf_sha256 = 'b'.repeat(64); },
    p => { p.published_commentary.word_attestation = true; }]) {
    const p = fixture(); change(p); assert.equal(find(p, 'ά').length, 0);
  }
});
test('uncertain OCR is excluded; duplicate literal headings all remain separate', () => {
  const p = fixture(), source = p.published_commentary;
  source.paragraphs.push({ ...source.paragraphs[0], text: 'Second source note with same heading.' }); source.paragraph_count++;
  assert.equal(find(p, 'ά').length, 2);
  source.paragraphs[0].uncertain_ocr = true; assert.equal(find(p, 'ά').length, 1);
  source.paragraphs[2].text = 'Broken � source'; assert.equal(find(p, 'ά').length, 0);
});
test('matching source text stays literal and no paid model or fetch is involved', () => {
  const p = fixture(), host = new Element('div');
  p.published_commentary.paragraphs[0].text = '<img src=x onerror=bad()> literal source';
  assert.equal(render(host, p, 'ά'), true);
  assert.ok(host.textContent.includes('<img src=x onerror=bad()>'));
  const flatten = element => [element, ...element.children.flatMap(flatten)];
  assert.equal(flatten(host).some(element => ['img', 'script', 'a'].includes(element.tag)), false);
});
