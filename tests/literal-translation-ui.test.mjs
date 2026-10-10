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
const scope = vm.createContext({ window: {}, URL, AbortController });
vm.runInContext(readFileSync(new URL('../js/passage-analysis.js', import.meta.url), 'utf8'), scope);
const render = scope.window.MelosPassageAnalysis.renderLiteralTranslation;
const flatten = element => [element, ...element.children.flatMap(flatten)];
// Synthetic wire shape; the strings are test fixtures, not a translation of any poem.
function fixture() {
  return { passage: { id: 'campbell:synthetic:1' }, literal_translation: {
    evidence_type: 'literal_machine_translation', scope: 'whole_poem_line_by_line', display_policy: 'fallback_only',
    model_eligible: false, selection_aligned: false, exact_edition_alignment: false, word_attestation: false,
    published_source: false, status: 'available', campbell_record_id: 'campbell:synthetic:1', line_aligned: true,
    published_english_available: false, translator: 'Synthetic model', produced_at: '2026-10-10',
    translation_status: 'unpublished machine translation', method: 'one English line per Greek line',
    line_count: 2, lines: [{ index: 0, label: '', greek: 'αβγ', english: 'first line' },
      { index: 1, label: '2', greek: 'δεζ', english: 'second line' }], text: 'first line\nsecond line', note: 'A note.', love_theme: true } };
}
test('fallback panel is closed by default, line-aligned, labelled as unpublished machine-made', () => {
  const data = fixture(), host = node('div'), original = JSON.stringify(data);
  assert.equal(render(host, data, node), true);
  const panel = host.children[0];
  assert.equal(panel.tag, 'details'); assert.equal(panel.open, undefined);
  assert.match(panel.textContent, /unpublished, machine-made/);
  assert.match(panel.textContent, /No published English translation of this poem/);
  assert.match(panel.textContent, /not used as evidence for word meanings/);
  const lines = flatten(panel).filter(element => element.cls === 'literal-line');
  assert.equal(lines.length, 2);
  assert.deepEqual(lines.map(line => line.children.map(child => child.text)), [['', 'αβγ', 'first line'], ['2', 'δεζ', 'second line']]);
  assert.equal(JSON.stringify(data), original);
});
test('published English present, wrong poem, evidence flags or a broken line list cannot show the fallback', () => {
  for (const change of [data => { data.literal_translation.published_english_available = true; },
    data => { data.literal_translation.campbell_record_id = 'other'; },
    data => { data.literal_translation.status = 'unavailable'; },
    data => { data.literal_translation.model_eligible = true; },
    data => { data.literal_translation.published_source = true; },
    data => { data.literal_translation.display_policy = 'always'; },
    data => { data.literal_translation.line_count = 3; },
    data => { data.literal_translation.lines[1].english = null; },
    data => { delete data.literal_translation; }]) {
    const data = fixture(), host = node('div'); change(data);
    assert.equal(render(host, data, node), false); assert.equal(host.children.length, 0);
  }
});
test('HTML-looking lines and notes are text, not markup', () => {
  const data = fixture(), host = node('div');
  data.literal_translation.lines[0].english = '<img src=x onerror=bad()> literal';
  data.literal_translation.note = '<script>bad()</script>';
  assert.equal(render(host, data, node), true);
  const texts = flatten(host).map(element => element.text);
  assert.ok(texts.includes('<img src=x onerror=bad()> literal'));
  assert.ok(texts.includes('<script>bad()</script>'));
  assert.ok(flatten(host).every(element => !['img', 'script'].includes(element.tag)));
});
// Reader order: the fallback renders only when neither published previews nor other-edition comparisons were shown.
const readerScript = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class ReaderElement extends Element {
  constructor(...args) { super(...args); this.hidden = false; }
}
function readerHarness(passage, analysis) {
  const ui = { related: new ReaderElement('div') };
  const context = vm.createContext({
    ui, state: { passage }, node: (tag, cls, text) => new ReaderElement(tag, cls, text), clear: element => element.replaceChildren(),
    globalThis: { window: { MelosPassageAnalysis: analysis } }, passageTranslationPreviews: record => record.translation_previews || [],
    renderPublishedTranslations: (host, items) => host.append(node('div', 'published-translations', String(items.length))),
    safeLink: (url, label) => Object.assign(node('a', '', label), { href: url }), chronologyClaim: () => null, qualityLabel: value => value,
  });
  vm.runInContext(readerScript.slice(readerScript.indexOf('  function renderRelated('), readerScript.indexOf('  function renderMirrors(')), context);
  return { ui, related: vm.runInContext('renderRelated', context) };
}
test('reader shows the fallback only when no published English was rendered', () => {
  const calls = [];
  const analysis = {
    renderTranslationComparisons: (host, data) => { calls.push('comparisons'); if (data.translation_comparisons) { host.append(node('div', 'translation-comparisons')); return true; } return false; },
    renderLiteralTranslation: (host, data) => { calls.push('literal'); if (!data.literal_translation) return false; host.append(node('div', 'literal-translation')); return true; },
  };
  const literal = fixture().literal_translation;
  // Nothing published: the fallback appears and the panel is visible.
  let harness = readerHarness({ id: 'campbell:synthetic:1', literal_translation: literal }, analysis);
  harness.related([]);
  assert.deepEqual(harness.ui.related.children.map(child => child.cls), ['literal-translation']);
  assert.equal(harness.ui.related.hidden, false);
  // Another-edition comparison shown: the fallback is not even attempted.
  calls.length = 0;
  harness = readerHarness({ id: 'campbell:synthetic:1', literal_translation: literal, translation_comparisons: { status: 'available' } }, analysis);
  harness.related([]);
  assert.deepEqual(harness.ui.related.children.map(child => child.cls), ['translation-comparisons']);
  assert.ok(!calls.includes('literal'));
  // Published previews shown: same.
  calls.length = 0;
  harness = readerHarness({ id: 'campbell:synthetic:1', kind: 'text', language: 'grc', literal_translation: literal,
    translation_previews: [{ record_id: 'p', parent_id: 'campbell:synthetic:1', scope: 'whole_source_passage', alignment: 'not_line_aligned',
      language: 'eng', text_excerpt: 'Published fixture.', text: 'Published fixture.' }] }, analysis);
  harness.related([]);
  assert.deepEqual(harness.ui.related.children.map(child => child.cls), ['published-translations']);
  assert.ok(!calls.includes('literal'));
  // The machine-translation corpus row never appears as related source material.
  harness = readerHarness({ id: 'campbell:synthetic:1' }, analysis);
  harness.related([{ id: 'campbell:synthetic:1:literal', kind: 'translation', language: 'eng', quality: 'machine_translation', text: 'x' }]);
  assert.equal(harness.ui.related.children.length, 0);
  assert.equal(harness.ui.related.hidden, true);
});
