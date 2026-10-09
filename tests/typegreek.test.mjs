import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

// js/typegreek.js must reproduce typegreek.com exactly (docs/typegreek-rules.md). The table holds 270
// keystroke sequences from the site's Alphabet Key and Overview pages; each expected value is what
// typegreek.com's own script produces when the keys are typed into an empty box with Greek on.
const require = createRequire(import.meta.url);
const TypeGreek = require('../js/typegreek.js');
const cases = JSON.parse(readFileSync(new URL('./fixtures/typegreek-cases.json', import.meta.url), 'utf8'));

test('TypeGreek rule table: at least 150 cases, all matching', () => {
  assert.ok(cases.length >= 150);
  const failures = cases.filter(([, keys, expected]) => TypeGreek.convert(keys) !== expected);
  assert.deepEqual(failures.map(([group, keys, expected]) => [group, keys, expected, TypeGreek.convert(keys)]), []);
});

test('output is NFC precomposed', () => {
  for (const [, keys] of cases) {
    const out = TypeGreek.convert(keys);
    assert.equal(out, out.normalize('NFC'), keys);
  }
  assert.equal(TypeGreek.convert('a)/|'), 'ᾄ');
  assert.equal(TypeGreek.convert('a/'), 'ά');
});

// Typing one key at a time through applyEdit (what the textarea does) equals converting the whole sequence.
function typeKeys(keys, greek = true) {
  let value = '', caret = 0;
  for (const ch of keys) {
    const next = value.slice(0, caret) + ch + value.slice(caret);
    const r = TypeGreek.applyEdit(value, next, caret + 1, caret + 1, greek);
    value = r.value; caret = r.start;
  }
  return { value, caret };
}

test('keystroke by keystroke equals the table, caret after the last character', () => {
  for (const [, keys, expected] of cases) {
    const r = typeKeys(keys);
    assert.equal(r.value, expected, keys);
    assert.equal(r.caret, expected.length, keys);
  }
});

test('order of diacritic keys does not matter', () => {
  for (const group of [['a)/|', 'a/|)', 'a|)/', 'a|/)', 'a/)|', 'a)|/'], ['w(=|', 'w|=(', 'w=(|', 'w(|=']]) {
    const outs = new Set(group.map(k => TypeGreek.convert(k)));
    assert.equal(outs.size, 1, group.join(' '));
  }
});

test('diacritic typed later attaches to the letter before the caret', () => {
  // "lo/gos " typed, then the caret moved after the omicron of "lo": typing "(" gives no change (λ
  // takes no breathing); after the alpha of "a" the rough breathing joins it.
  let r = TypeGreek.applyEdit('α λόγος ', '(α λόγος ', 1, 1, true);
  assert.equal(r.value, '῾α λόγος ');
  r = TypeGreek.applyEdit('α λόγος ', 'α( λόγος ', 2, 2, true);
  assert.deepEqual(r, { value: 'ἁ λόγος ', start: 1, end: 1 });
});

test('final sigma follows what comes after it', () => {
  assert.equal(TypeGreek.convert('logos'), 'λογοσ');          // end of the box: still σ, as on typegreek.com
  assert.equal(TypeGreek.convert('logos '), 'λογος ');
  assert.equal(TypeGreek.convert('logosk'), 'λογοσκ');
  // deleting the space after a final sigma turns it back into σ
  assert.equal(TypeGreek.applyEdit('λογος κ', 'λογοςκ', 5, 5, true).value, 'λογοσκ');
});

test('English mode leaves Latin letters and keys alone', () => {
  assert.equal(typeKeys('hello / world?', false).value, 'hello / world?');
});

test('pasted Latin is converted; pasted Greek is left alone', () => {
  const pasteLatin = TypeGreek.applyEdit('', 'mh=nin a)/eide qea\\ ', 20, 20, true);
  assert.equal(pasteLatin.value, 'μῆνιν ἄειδε θεὰ ');
  assert.equal(pasteLatin.start, pasteLatin.value.length);
  const greek = 'πόλεως— (Il. 1.1)';
  const pasteGreek = TypeGreek.applyEdit('', greek, greek.length, greek.length, true);
  assert.equal(pasteGreek.value, greek);
  const nfd = 'ἄειδε'.normalize('NFD');
  assert.equal(TypeGreek.applyEdit('', nfd, nfd.length, nfd.length, true).value, 'ἄειδε');
});

test('mobile: a word committed by the keyboard (composition or autocorrect) converts as a whole', () => {
  // Gboard composes "logos" then commits it; the space follows as its own input.
  let r = TypeGreek.applyEdit('καὶ ', 'καὶ logos', 9, 9, true);
  assert.deepEqual(r, { value: 'καὶ λογοσ', start: 9, end: 9 });
  r = TypeGreek.applyEdit(r.value, r.value + ' ', 10, 10, true);
  assert.equal(r.value, 'καὶ λογος ');
  // the keyboard recomposes an existing Greek word and appends a Latin letter
  r = TypeGreek.applyEdit('λογο', 'λογοs', 5, 5, true);
  assert.equal(r.value, 'λογοσ');
  // a Latin suggestion from the keyboard's strip replaces the word before the caret (insertReplacementText)
  r = TypeGreek.applyEdit('καὶ λγοσ', 'καὶ logos ', 10, 10, true);
  assert.deepEqual(r, { value: 'καὶ λογος ', start: 10, end: 10 });
});

test('the module stands alone: no imports, no globals besides TypeGreek', () => {
  const src = readFileSync(new URL('../js/typegreek.js', import.meta.url), 'utf8');
  assert.doesNotMatch(src, /\bimport\b|\brequire\(|melos-api|fetch\(/);
  assert.match(src, /try \{ const saved = localStorage\.getItem/);
  assert.match(src, /try \{ localStorage\.setItem/);
});
