import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic rows only: checks the dictionary-order headline, not Greek claims.
const window = {};
vm.runInNewContext(readFileSync(new URL('../js/passage-analysis.js', import.meta.url), 'utf8'), { window, AbortController });
const { headlineFromRow, renderWordHeadline } = window.MelosPassageAnalysis;
class Element {
  constructor(tag, className = '', text = '') { Object.assign(this, { tag, className, text, children: [], attributes: {} }); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(name, value) { this.attributes[name] = value; }
  get textContent() { return this.text + this.children.map(item => item.textContent).join(''); }
}
const node = (tag, cls, text) => new Element(tag, cls, text);
const lines = host => host.children[0].children.map(item => [item.className.split(' ')[0], item.textContent]);

test('headline shows headword, then its short gloss, then printed form and parse', () => {
  const host = node('div');
  renderWordHeadline(host, headlineFromRow({ kind: 'word', text: 'βγ', lemma: 'αβ', parse_short: 'acc. fem. sg.',
    gloss: { status: 'available', text: 'thing', source: 'LSJ' } }), node);
  assert.deepEqual(lines(host), [['word-title', 'αβ'], ['word-headline-gloss', 'thing'], ['word-headline-form', 'βγ'],
    ['word-headline-parse', 'acc. fem. sg.']]);
});

test('missing gloss is a quiet placeholder and capitalised headwords are proper names', () => {
  const quiet = node('div'), name = node('div');
  renderWordHeadline(quiet, headlineFromRow({ kind: 'word', text: 'βγ', lemma: 'αβ', gloss: { status: 'unavailable' } }), node);
  assert.deepEqual(lines(quiet)[1], ['word-headline-gloss', 'no short gloss']);
  assert.match(quiet.children[0].children[1].className, /word-headline-empty/);
  assert.deepEqual(lines(quiet)[3], ['word-headline-parse', 'parse not settled']);
  renderWordHeadline(name, headlineFromRow({ kind: 'word', text: 'Ἀβ', lemma: 'Ἄβος', parse_short: 'nom. masc. sg.',
    gloss: { status: 'available', text: 'a' } }), node);
  assert.deepEqual(lines(name)[1], ['word-headline-gloss', '(proper name)']);
});

test('pending headline holds the gloss slot without inventing a meaning', () => {
  const host = node('div');
  renderWordHeadline(host, { form: 'βγ', pending: true }, node);
  assert.deepEqual(lines(host), [['word-title', 'βγ'], ['word-headline-gloss', 'Looking up meaning…']]);
  assert.equal(headlineFromRow({ kind: 'punct', text: ',' }), null);
});

test('headline prefers the short dictionary head phrase and keeps the full text in the title', () => {
  const host = node('div');
  renderWordHeadline(host, headlineFromRow({ kind: 'word', text: 'βγ', lemma: 'αβ', parse_short: 'nom. neut. sg.',
    gloss: { status: 'available', text: 'a piece of land cut off', short_text: 'a piece of land', source: 'ML' } }), node);
  assert.deepEqual(lines(host)[1], ['word-headline-gloss', 'a piece of land']);
  assert.match(host.children[0].children[1].title, /^a piece of land cut off/);
  const fallback = headlineFromRow({ kind: 'word', text: 'βγ', lemma: 'αβ', gloss: { status: 'available', text: 'thing', short_text: ' ' } });
  assert.equal(fallback.gloss, 'thing');
  assert.equal(window.MelosPassageAnalysis.shortGlossText({ status: 'unavailable', short_text: 'x' }), '');
});
