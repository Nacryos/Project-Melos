import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic presentation fixtures; no new corpus records or source identities.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div', cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [], handlers: {}, hidden: true }); }
  append(...children) { this.children.push(...children); }
  addEventListener(event, callback) { this.handlers[event] = callback; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const descendants = root => root.children.flatMap(child => [child, ...descendants(child)]);
function harness() {
  const opened = [], ui = { related: new Element() };
  const context = vm.createContext({ ui,
    node: (tag, cls, text) => new Element(tag, cls, text),
    chronologyClaim: () => null, qualityLabel: value => value,
    passageTranslationPreviews: () => [], openPassage: id => opened.push(id),
    safeLink(url, label) { const link = new Element('a', '', label); link.href = url; return link; },
  });
  vm.runInContext(script.slice(script.indexOf('  function renderResult('), script.indexOf('  function renderDictionaryPreview('))
    + script.slice(script.indexOf('  function renderMirrors('), script.indexOf('  async function openPassage(')), context);
  return { opened, ui, render: vm.runInContext('renderResult', context), mirrors: vm.runInContext('renderMirrors', context) };
}
const record = (id, changes = {}) => ({ id, author: 'Synthetic author', work: 'Synthetic work', citation: '187',
  text: 'Same synthetic wording', kind: 'text', language: 'grc', source: 'Synthetic collection',
  edition: 'Synthetic edition', ...changes });

test('reference cards expose distinct source editions without grouping or changing identities', () => {
  const records = [record('one', { edition: 'First source edition' }),
    record('two', { edition: 'Second source edition' }),
    record('three', { author: 'synthetic author', work: 'source work label', source: 'Mirror collection', edition: 'Mirror source edition' })]
    .map(item => ({ ...item, reference_match: { number: '187', scheme: null, evidence: ['187'], coverage: 'text' } }));
  const before = structuredClone(records), h = harness(), cards = records.map(h.render);
  assert.equal(cards.length, 3);
  for (let index = 0; index < cards.length; index++) {
    const card = cards[index], source = records[index];
    assert.ok(card.textContent.includes(`Edition: ${source.edition}`));
    assert.ok(card.textContent.includes(`Collection: ${source.source}`));
    assert.ok(card.textContent.includes(source.author)); assert.ok(card.textContent.includes(source.citation));
    assert.equal(descendants(card).filter(item => ['a', 'button', 'summary'].includes(item.tag)).length, 0);
    card.handlers.click(); assert.equal(h.opened.at(-1), source.id);
  }
  assert.deepEqual(records, before);
});

test('ordinary grouped results retain mirror metadata and show the representative exact edition', () => {
  const input = record('one', { mirror_count: 3, mirrored_ids: ['one', 'two', 'three'] });
  const before = structuredClone(input), card = harness().render(input);
  assert.match(card.textContent, /Edition: Synthetic edition/); assert.match(card.textContent, /Collection: Synthetic collection/);
  assert.match(card.textContent, /2 identical copies collapsed/); assert.deepEqual(input, before);
});

test('missing and hostile source labels remain honest literal text, not guessed identities or markup', () => {
  const h = harness(), missing = h.render(record('missing', { edition: '', source: null }));
  assert.match(missing.textContent, /Edition: Not supplied/); assert.match(missing.textContent, /Collection: Not supplied/);
  const hostile = h.render(record('hostile', { edition: '<img onerror=unsafe()>', source: '<script>unsafe()</script>' }));
  assert.match(hostile.textContent, /Edition: <img onerror=unsafe\(\)>/);
  assert.match(hostile.textContent, /Collection: <script>unsafe\(\)<\/script>/);
  assert.equal(descendants(hostile).filter(item => ['script', 'img'].includes(item.tag)).length, 0);
});

test('reader copy description makes no universal search grouping or numbering-equivalence claim', () => {
  const h = harness(); h.mirrors([record('copy', { source_url: 'https://example.test/copy' })]);
  assert.match(h.ui.related.textContent, /Identical wording is shown together here; each copy retains its own source and citation\./);
  assert.doesNotMatch(h.ui.related.textContent, /Copies are grouped in search results|equivalent edition|same numbering/);
  descendants(h.ui.related).find(item => item.tag === 'button').handlers.click(); assert.equal(h.opened.at(-1), 'copy');
});

test('source labels wrap in the result body instead of expanding the narrow author column', () => {
  const card = harness().render(record('long', { edition: 'LongSourceEdition'.repeat(30) }));
  const body = descendants(card).find(item => item.cls === 'result-body');
  assert.ok(descendants(body).some(item => item.cls === 'result-edition'));
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  assert.match(css, /\.result-edition,\.result-collection\{[^}]*overflow-wrap:anywhere/);
});
