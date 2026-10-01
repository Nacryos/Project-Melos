import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Literal synthetic UI fixtures only; no invented corpus translations.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div', cls = '', text = '') {
    Object.assign(this, { tag, cls, text, children: [], handlers: {}, dataset: {}, hidden: false });
  }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; this.text = ''; }
  addEventListener(event, callback) { this.handlers[event] = callback; }
  querySelector(selector) { return descendants(this).find(child => child.cls === selector.slice(1)) || null; }
  scrollIntoView() { this.scrolled = true; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
function descendants(root) { return root.children.flatMap(child => [child, ...descendants(child)]); }
function fixture() {
  return { id: 'fixture:greek', kind: 'text', language: 'grc', author: 'Fixture poet', text: 'Literal Greek fixture',
    translation_previews: [{ record_id: 'fixture:translation', parent_id: 'fixture:greek', scope: 'whole_source_passage',
      alignment: 'not_line_aligned', language: 'ell', translator: 'Fixture credited translator',
      text_excerpt: 'Literal published fixture excerpt.', text: 'Literal published fixture excerpt.\nEntire second fixture line.',
      source_url: 'https://example.test/translation#pane', edition: 'Fixture edition', citation: 'Fixture source passage' }] };
}
function harness(record = fixture()) {
  const ui = { related: new Element(), selectionActions: new Element() };
  const state = { passage: record, selectedText: 'partial fixture phrase', passageLoading: false };
  const opened = [];
  const context = vm.createContext({
    ui, state, node: (tag, cls, text) => new Element(tag, cls, text), clear: element => element.replaceChildren(),
    chronologyClaim: () => null, qualityLabel: value => value, openPassage: id => opened.push(id),
    safeLink(url, label) { const link = new Element('a', '', label); link.href = url; return link; }
  });
  vm.runInContext(script.slice(script.indexOf('  function renderRelated('), script.indexOf('  function renderMirrors(')), context);
  vm.runInContext(script.slice(script.indexOf('  function renderResult('), script.indexOf('  function renderDictionaryPreview(')), context);
  vm.runInContext(script.slice(script.indexOf('  function updateSelectionTranslationAction('), script.indexOf('  function updateSelection(')), context);
  return { ui, state, opened, render: vm.runInContext('renderResult', context),
    related: vm.runInContext('renderRelated', context), selection: vm.runInContext('updateSelectionTranslationAction', context) };
}

test('result card uses a literal credited whole-passage excerpt, without nested links or controls', () => {
  const h = harness(), result = h.render(h.state.passage);
  assert.equal(result.tag, 'button');
  assert.match(result.textContent, /Literal published fixture excerpt/);
  assert.match(result.textContent, /Modern Greek · Translator: Fixture credited translator/);
  assert.match(result.textContent, /Published translation excerpt · covers this source passage/);
  assert.equal(descendants(result).filter(element => ['a', 'button', 'summary'].includes(element.tag)).length, 0);
  result.handlers.click(); assert.equal(h.opened[0], 'fixture:greek');
});

test('unknown translator remains explicit and no mirror/wrong-parent/line-aligned projection is accepted', () => {
  const record = fixture(); record.translation_previews[0].translator = null;
  const h = harness(record);
  assert.match(h.render(record).textContent, /Translator not recorded/);
  for (const alteration of [{ parent_id: 'another-record' }, { scope: 'same_number' }, { alignment: 'line_aligned' }]) {
    const wrong = fixture(); Object.assign(wrong.translation_previews[0], alteration);
    assert.ok(!h.render(wrong).textContent.includes('Literal published fixture excerpt'));
  }
});

test('audited English preview retains its own source credit and full translation', () => {
  const record = fixture();
  Object.assign(record.translation_previews[0], {
    source: 'perseus', language: 'eng', translator: 'Fixture English translator',
    source_url: 'https://example.test/perseus/translation.xml',
    scope_note: "Published translation covering this source passage; not aligned to individual lines or a selected phrase. The translator's Greek base edition is not established here."
  });
  const h = harness(record);
  assert.match(h.render(record).textContent, /English · Translator: Fixture English translator/);
  h.related([]);
  const full = h.ui.related.querySelector('.translation-full');
  assert.match(full.textContent, /Entire second fixture line/);
  assert.match(full.textContent, /Greek base edition is not established here/);
  assert.equal(descendants(full).find(element => element.tag === 'a').href,
    'https://example.test/perseus/translation.xml');
  assert.ok(!h.ui.related.textContent.includes('Modern Greek'));
});

test('published translation is promoted before notes, its full literal text is expandable, and duplicate inline copy is removed', () => {
  const h = harness();
  h.related([{ id: 'fixture:translation', parent_id: 'fixture:greek', kind: 'translation', text: 'Must not repeat in generic related section' },
    { id: 'note', kind: 'commentary', text: 'Separate fixture note', metadata: { scope: 'source_section' } }]);
  const section = h.ui.related.children[0];
  assert.equal(section.cls, 'published-translations');
  assert.match(section.textContent, /not aligned to individual lines or a selected phrase/);
  const details = section.querySelector('.translation-full');
  assert.equal(details.open, undefined);
  assert.match(details.textContent, /Entire second fixture line/);
  assert.equal(descendants(details).find(element => element.tag === 'a').href, 'https://example.test/translation#pane');
  assert.ok(!h.ui.related.textContent.includes('Must not repeat'));
  assert.match(h.ui.related.textContent, /Separate fixture note/);
});

test('additional translator versions stay separate and collapsed rather than combined', () => {
  const record = fixture();
  record.translation_previews.push({ ...record.translation_previews[0], record_id: 'fixture:second',
    translator: 'Second fixture translator', text: 'Different full fixture translation.' });
  const h = harness(record); h.related([]);
  const alternatives = h.ui.related.querySelector('.translation-alternatives');
  assert.equal(alternatives.open, undefined);
  assert.match(alternatives.textContent, /1 other published translation/);
  assert.match(alternatives.textContent, /Second fixture translator/);
  assert.equal(h.ui.related.hidden, false);
});

test('partial selection opens the containing translation, not a purported translation of selected words', () => {
  const h = harness(); h.related([]); h.selection();
  const button = h.ui.selectionActions.querySelector('.selection-translation');
  assert.equal(button.textContent, 'Containing passage translation');
  assert.match(button.title, /not aligned to this selection/);
  button.handlers.click();
  assert.equal(h.ui.related.querySelector('.translation-full').open, true);
  assert.equal(h.ui.related.querySelector('.published-translations').scrolled, true);
  h.state.passage = null; h.selection();
  assert.equal(button.hidden, true);
  assert.doesNotThrow(() => button.handlers.click());
});

test('full translation disclosure hides the duplicate excerpt by open state, including programmatic opening', () => {
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  assert.match(css, /\.published-translation:has\(>\.translation-full\[open\]\)>\.translation-excerpt\{display:none\}/);
  const h = harness(); h.related([]); h.selection();
  h.ui.selectionActions.querySelector('.selection-translation').handlers.click();
  const article = h.ui.related.querySelector('.published-translation');
  assert.equal(article.children.find(child => child.cls === 'translation-full').open, true);
  assert.ok(article.children.find(child => child.cls === 'translation-excerpt'));
  assert.ok(article.children.find(child => child.cls === 'translation-credit'));
  // Native details closing removes [open], so the same CSS rule stops hiding
  // the excerpt without another request or mutation of either source text.
  article.querySelector('.translation-full').open = false;
  assert.equal(article.querySelector('.translation-full').open, false);
});

test('translation markup is only text and no generated or word-gloss fallback is introduced', () => {
  const record = fixture(); record.translation_previews[0].text_excerpt = '<b>Literal source markup fixture</b>';
  const h = harness(record), result = h.render(record);
  assert.match(result.textContent, /<b>Literal source markup fixture<\/b>/);
  assert.equal(descendants(result).filter(element => element.tag === 'b').length, 0);
  delete record.translation_previews;
  assert.equal(descendants(h.render(record)).filter(element => element.cls === 'result-translation').length, 0);
});
