import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic strings test mechanics only; they are not literary evidence.
const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('  function literalGreekWords('), source.indexOf('  function appendTextWithWords(')), context);
const words = vm.runInContext('readingWords', context);

test('brackets inside a word keep it one unit; a lacuna between letters still splits it', () => {
  for (const [text, form] of [['α[β]γ', 'αβγ'], ['α⟨β⟩γ', 'αβγ']]) {
    const units = words(text);
    assert.equal(units.length, 1, text);
    assert.equal(units[0].text, text);
    assert.equal(units[0].form, form);
    assert.equal(units[0].fragmentaryJoinRejected, undefined, text);
  }
  const gap = words('α[…]β');
  assert.deepEqual(Array.from(gap, unit => unit.text), ['α[', ']β']);
  assert.ok(gap.every(unit => unit.fragmentaryJoinRejected && !unit.joined));
  assert.ok(gap.every(unit => 'α[…]β'.slice(unit.start, unit.end) === unit.text));
});

test('underdots stay in the printed unit and are left out of the lookup key', () => {
  const units = words('α̣β γ́ δ̓');
  assert.equal(units[0].text, 'α̣β');
  assert.equal(units[0].form, 'αβ');
  assert.equal(units[0].fragmentaryJoinRejected, undefined);
  assert.equal(units[1].form, 'γ́');
  assert.equal(units[2].form, 'δ̓');
});

test('isolated accents are not buttons and supplied whole words retain behavior', () => {
  const text = '…́ α [β] γ';
  const units = words(text);
  assert.deepEqual(Array.from(units, unit => unit.text), ['α', '[β]', 'γ']);
  assert.deepEqual(Array.from(units, unit => unit.form), ['α', 'β', 'γ']);
  assert.ok(units.every(unit => !unit.fragmentaryJoinRejected));
});
