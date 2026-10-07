import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic strings test mechanics only; they are not literary evidence.
const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('  function literalGreekWords('), source.indexOf('  function appendTextWithWords(')), context);
const words = vm.runInContext('readingWords', context);

test('every bracket-interrupted segment uses the existing incomplete-word display', () => {
  for (const text of ['α[β]γ', 'α⟨β⟩γ', 'α[…]β']) {
    const units = words(text);
    assert.ok(units.every(unit => unit.fragmentaryJoinRejected), text);
    assert.ok(units.every(unit => !unit.joined && unit.form === unit.text), text);
    assert.ok(units.every(unit => text.slice(unit.start, unit.end) === unit.text), text);
  }
});

test('underdots indicate uncertain source letters, not ordinary accents', () => {
  const units = words('α\u0323β γ\u0301 δ\u0313');
  assert.equal(units[0].fragmentaryJoinRejected, true);
  assert.equal(units[1].fragmentaryJoinRejected, undefined);
  assert.equal(units[2].fragmentaryJoinRejected, undefined);
});

test('isolated accents are not buttons and supplied whole words retain behavior', () => {
  const text = '…\u0301 α [β] γ';
  const units = words(text);
  assert.deepEqual(Array.from(units, unit => unit.text), ['α', 'β', 'γ']);
  assert.ok(units.every(unit => !unit.fragmentaryJoinRejected));
});
