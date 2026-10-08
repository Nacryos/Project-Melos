import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic UI mechanics only, never Greek corpus data or invented commentary.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') {
    Object.assign(this, { tag, cls, text, children: [], handlers: {} });
  }
  append(...children) { this.children.push(...children); }
  addEventListener(event, callback) { this.handlers[event] = callback; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const descendants = root => root.children.flatMap(child => [child, ...descendants(child)]);
function harness() {
  const opened = [];
  const context = vm.createContext({
    node: (tag, cls, text) => new Element(tag, cls, text),
    chronologyClaim: () => null, qualityLabel: value => value,
    passageTranslationPreviews: () => [], openPassage: id => opened.push(id),
  });
  vm.runInContext(script.slice(script.indexOf('  function renderResult('),
    script.indexOf('  function renderDictionaryPreview(')), context);
  return { render: vm.runInContext('renderResult', context), opened };
}
function hit(overrides = {}) {
  return { id: 'fixture:note', kind: 'commentary', signal: 'semantic',
    author: 'Fixture commentator', citation: 'Fixture note 1', edition: 'Fixture edition',
    source_url: 'https://example.test/note', parent_id: 'fixture:poem',
    projection_scope: 'explicit_parent_id', text_excerpt: 'Literal fixture commentary excerpt.',
    excerpt_truncated: false, match_reason: 'Retrieval similarity', ...overrides };
}
function poem(evidence = [hit()]) {
  return { id: 'fixture:poem', kind: 'text', language: 'grc', author: 'Fixture poet',
    text: 'Original fixture reading', matched_evidence: evidence };
}

test('Greek result shows literal credited commentary separately and opens only the Greek record', () => {
  const record = poem(), before = structuredClone(record), h = harness(), card = h.render(record);
  assert.deepEqual(record, before);
  assert.match(card.textContent, /Original fixture reading/);
  assert.match(card.textContent, /Commentary excerpt · Fixture commentator/);
  assert.match(card.textContent, /Fixture note 1 · Fixture edition/);
  assert.match(card.textContent, /Literal fixture commentary excerpt\./);
  assert.match(card.textContent, /Matched source excerpts/);
  assert.match(card.textContent, /Linked passage; not word-aligned/);
  assert.doesNotMatch(card.textContent, /Source attribution:|source parent ID|meaning of the Greek/);
  assert.doesNotMatch(card.textContent, /Published translation excerpt/);
  assert.equal(card.tag, 'button');
  assert.equal(descendants(card).filter(item => ['a', 'button', 'summary'].includes(item.tag)).length, 0);
  card.handlers.click(); assert.deepEqual(h.opened, ['fixture:poem']);
});

test('matched translation remains search evidence, without inventing translator credit', () => {
  const card = harness().render(poem([hit({ kind: 'translation', language: 'eng', author: 'Recorded source author',
    text_excerpt: '<b>Literal translation fixture</b>', excerpt_truncated: true })]));
  assert.match(card.textContent, /Translation excerpt · Recorded source author/);
  assert.match(card.textContent, /<b>Literal translation fixture<\/b>/);
  assert.match(card.textContent, /Excerpt shortened/);
  assert.doesNotMatch(card.textContent, /Translator:|Published translation excerpt/);
  assert.equal(descendants(card).filter(item => item.tag === 'b').length, 0);
});

test('non-English and unlabelled translation snippets are not shown as English meaning', () => {
  for (const language of ['ell', 'el', 'grc', '', undefined]) {
    const card = harness().render(poem([hit({ kind: 'translation', language, text_excerpt: 'NON_ENGLISH_FIXTURE' })]));
    assert.doesNotMatch(card.textContent, /NON_ENGLISH_FIXTURE|Translation excerpt/);
    assert.match(card.textContent, /Original fixture reading/);
  }
  assert.match(harness().render(poem([hit({ kind: 'translation', language: 'en-GB', text_excerpt: 'English regional fixture' })])).textContent, /English regional fixture/);
});

test('unproven, pagewide, wrong-parent and non-Greek result snippets do not get projected', () => {
  for (const altered of [
    { projection_scope: 'direct_record' }, { projection_scope: 'source_page' },
    { projection_scope: undefined }, { parent_id: 'fixture:unrelated' },
    { parent_id: null }, { kind: 'text' }, { id: 'fixture:poem' },
  ]) assert.doesNotMatch(harness().render(poem([hit(altered)])).textContent, /Literal fixture commentary excerpt/);
  for (const altered of [{ kind: 'commentary' }, { language: 'eng' }]) {
    assert.doesNotMatch(harness().render({ ...poem(), ...altered }).textContent, /Literal fixture commentary excerpt/);
  }
});

test('mirror-parent evidence states edition scope instead of claiming the selected source link', () => {
  const record = { ...poem([hit({ parent_id: 'fixture:mirror' })]), mirrored_ids: ['fixture:mirror'] };
  const card = harness().render(record);
  assert.match(card.textContent, /Literal fixture commentary excerpt/);
  assert.match(card.textContent, /another indexed reading; compare editions/);
  assert.doesNotMatch(card.textContent, /Linked passage;/);
});

test('source IDs deduplicate signals, never distinct quotations with identical credit', () => {
  const record = poem([
    hit({ id: 'fixture:direct', kind: 'text', projection_scope: 'direct_record' }),
    hit(), hit({ signal: 'lexical' }),
    hit({ id: 'fixture:second', text_excerpt: 'Second literal fixture quotation.' }),
    hit({ id: 'fixture:third', text_excerpt: 'Third literal fixture quotation.' }),
    hit({ id: 'fixture:fourth', text_excerpt: 'Fourth bounded fixture quotation.' }),
  ]);
  const card = harness().render(record);
  assert.equal(descendants(card).filter(item => item.cls === 'evidence-hit').length, 3);
  assert.equal(card.textContent.split('Matched source excerpts').length - 1, 1);
  assert.equal(card.textContent.split('Literal fixture commentary excerpt.').length - 1, 1);
  assert.match(card.textContent, /Second literal fixture quotation/);
  assert.match(card.textContent, /Third literal fixture quotation/);
  assert.doesNotMatch(card.textContent, /Fourth bounded fixture quotation/);
});

test('missing authors remain explicit; old backend evidence retains its existing label', () => {
  const card = harness().render(poem([hit({ author: null })]));
  assert.match(card.textContent, /Author not recorded/);
  const old = harness().render(poem([hit({ text_excerpt: undefined, projection_scope: undefined })]));
  assert.match(old.textContent, /Similar meaning · commentary · Fixture commentator · Fixture note 1: Retrieval similarity/);
  assert.doesNotMatch(old.textContent, /Linked passage;|Matched source excerpts/);
});

test('retrieval terms are shown in plain words; unknown reasons pass through unchanged', () => {
  const render = harness().render;
  const fused = render({ ...poem([]), match_reason: 'lexical + forms + semantic; direct passage match',
    retrieval_score_kind: 'reciprocal_rank_fusion' }).textContent;
  assert.match(fused, /Same words, related word forms and similar meaning, found in the Greek text/);
  assert.match(fused, /the order is not a measure of certainty/);
  assert.doesNotMatch(fused, /reciprocal rank|lexical \+|direct passage match/);
  const bridged = render({ ...poem([]), match_reason: 'semantic; linked translation/commentary evidence' }).textContent;
  assert.match(bridged, /Similar meaning, found through a linked translation or commentary/);
  const signal = render(poem([hit({ parent_id: 'elsewhere', signal: 'lexical', match_reason: 'Normalized wording / citation match' })])).textContent;
  assert.match(signal, /Same words · commentary · Fixture commentator · Fixture note 1: same wording, ignoring accents and capitals/);
  assert.match(render({ ...poem([]), match_reason: 'Fixture backend reason' }).textContent, /Fixture backend reason/);
});
