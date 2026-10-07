import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [] }); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const node = (...args) => new Element(...args);
const safeLink = (url, text) => Object.assign(node('a', '', text), { href: url });
const scope = vm.createContext({ window: {}, URL, AbortController });
vm.runInContext(readFileSync(new URL('../js/passage-analysis.js', import.meta.url), 'utf8'), scope);
const render = scope.window.MelosPassageAnalysis.renderTranslationComparisons;
// Synthetic English/source metadata test contracts, not translations of Greek.
function fixture() {
  const flags = { evidence_type: 'different_edition_translation_comparison', scope: 'whole_poem_other_edition',
    selection_aligned: false, exact_edition_alignment: false, word_attestation: false, line_attestation: false, model_eligible: false };
  return { passage: { id: 'campbell:synthetic:1' }, translation_comparisons: { ...flags, status: 'available',
    campbell_record_id: 'campbell:synthetic:1', comparison_count: 1, translation_comparisons: [{ ...flags,
      comparison_id: 'other-edition:synthetic:1', language: 'eng', text: 'Unchanged source English.\n'.repeat(50),
      translator: 'Synthetic translator', citation: 'Other edition, fragment Z', edition: 'Synthetic other edition',
      source_url: 'https://example.test/source', license: 'Synthetic rights metadata', source_notes: [], paired_greek: null }] } };
}
test('whole English comparison is closed by default, fully preserved, credited and explicitly another edition', () => {
  const data = fixture(), host = node('div'), original = JSON.stringify(data);
  assert.equal(render(host, data, node, safeLink), true);
  const panel = host.children[0], item = data.translation_comparisons.translation_comparisons[0];
  assert.equal(panel.tag, 'details'); assert.equal(panel.open, undefined);
  assert.ok(panel.textContent.includes(item.text)); assert.match(panel.textContent, /Translator: Synthetic translator/);
  assert.match(panel.textContent, /not translations aligned to Campbell’s text or to the selected words/);
  const flatten = element => [element, ...element.children.flatMap(flatten)];
  assert.equal(flatten(panel).find(element => element.tag === 'a').href, item.source_url);
  assert.equal(JSON.stringify(data), original);
});
test('analysis context wire shape works and explicit context absence cannot fall back to another wrapper', () => {
  const data = fixture(), wrapper = data.translation_comparisons;
  delete data.translation_comparisons; data.context = { translation_comparisons: wrapper };
  assert.equal(render(node('div'), data, node, safeLink), true);
  data.translation_comparisons = wrapper; data.context.translation_comparisons = null;
  assert.equal(render(node('div'), data, node, safeLink), false);
});
test('wrong poem, alignment flags, non-English text metadata and unsafe links cannot become comparisons', () => {
  for (const change of [data => { data.translation_comparisons.campbell_record_id = 'other'; },
    data => { data.translation_comparisons.selection_aligned = true; },
    data => { data.translation_comparisons.translation_comparisons[0].exact_edition_alignment = true; },
    data => { data.translation_comparisons.translation_comparisons[0].model_eligible = true; },
    data => { data.translation_comparisons.translation_comparisons[0].language = 'ell'; },
    data => { data.translation_comparisons.translation_comparisons[0].source_url = 'javascript:bad()'; },
    data => { data.translation_comparisons.translation_comparisons[0].parent_id = data.passage.id; },
    data => { data.translation_comparisons.comparison_count = 9; }]) {
    const data = fixture(), host = node('div'); change(data);
    assert.equal(render(host, data, node, safeLink), false); assert.equal(host.children.length, 0);
  }
});
test('HTML-looking translation, credit and source notes are text, not executable markup', () => {
  const data = fixture(), item = data.translation_comparisons.translation_comparisons[0], host = node('div');
  item.text = '<img src=x onerror=bad()> literal English'; item.translator = '<script>bad()</script>';
  item.source_notes = [{ text: '<svg onload=bad()> note', source_url: 'javascript:bad()' }];
  assert.equal(render(host, data, node, safeLink), true);
  const flatten = element => [element, ...element.children.flatMap(flatten)];
  assert.equal(flatten(host).some(element => ['img', 'script', 'svg'].includes(element.tag)), false);
  assert.ok(host.textContent.includes(item.text)); assert.ok(host.textContent.includes(item.source_notes[0].text));
  assert.equal(flatten(host).filter(element => element.tag === 'a').length, 1);
});
test('poem-load related panel exposes comparison even without ordinary related records or exact translation previews', () => {
  const data = fixture(), ui = { related: node('div') };
  const context = vm.createContext({ window: scope.window, ui, state: { passage: { ...data.passage, translation_comparisons: data.translation_comparisons } },
    node, safeLink, clear: element => element.replaceChildren() });
  const reader = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
  vm.runInContext(reader.slice(reader.indexOf('  function renderRelated('), reader.indexOf('  async function openPassage(')), context);
  context.renderRelated([]);
  assert.equal(ui.related.hidden, false); assert.match(ui.related.textContent, /English translation · another edition/);
  assert.equal(ui.related.children[0].tag, 'details');
});
