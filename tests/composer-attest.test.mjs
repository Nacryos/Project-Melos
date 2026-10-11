import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const scope = vm.createContext({ window: {}, URL });
vm.runInContext(readFileSync(new URL('../js/composer-core.js', import.meta.url), 'utf8'), scope);
const C = scope.window.ComposerCore || scope.ComposerCore;
// Shapes copied from the lint bank's answers (backend/composer_lint.py L1 / L2 / L4 evidence); synthetic counts.
function checks() {
  return [
    { id: 'L7', ok: true, evidence: [] },
    { id: 'L1', ok: true, evidence: [{ form: 'κόρ᾽', reading: 'morpheus', lemmas: ['κόρη', 'κόρος'] }, { form: 'ὄρεισα', reading: 'morpheus', lemmas: ['ὁράω'] },
      { form: 'ξζψ', reading: null }, { form: 'βραδύ', reading: 'timeout' }] },
    { id: 'L2', ok: false, evidence: [{ form: 'σελήνη', dialect_spellings: [{ form: 'σελάννα', example: 'Sappho 154' }] }, { form: 'βραδύ', reading: 'timeout' }] },
    { id: 'L4', ok: true, evidence: [
      { form: 'ἄγνα', tokens: 13, dialect_tokens: 9, author_tokens: 7, example: { author: 'Sappho', citation: '2' } },
      { form: 'πεδ᾽', tokens: 54, dialect_tokens: 11, author_tokens: 0, example: { author: 'Alcaeus', citation: '130b' } },
      { form: 'κοῦφον', tokens: 50, dialect_tokens: 0, author_tokens: 0, example: null },
      { form: 'κόρ᾽', tokens: 0, dialect_tokens: null, author_tokens: null, example: null },
      { form: 'ὄρεισα', tokens: 0, dialect_tokens: null, author_tokens: null, example: null },
      { form: 'σελήνη', tokens: 84, dialect_tokens: 0, author_tokens: 0, example: null }] },
  ];
}
test('attestation verdicts per word from the lint evidence', () => {
  const v = C.attestWords(checks(), { author: 'Sappho', dialect: 'Lesbian' });
  const level = form => v.get(form)?.level;
  assert.equal(level('ἄγνα'), 'ok'); assert.match(v.get('ἄγνα').note, /7× by Sappho \(Sappho 2\)/);
  assert.equal(level('πεδ᾽'), 'ok'); assert.match(v.get('πεδ᾽').note, /11× by Lesbian poets/);
  assert.equal(level('κοῦφον'), 'warn'); assert.match(v.get('κοῦφον').note, /never by a Lesbian poet/);
  assert.equal(level('κόρ᾽'), 'warn'); assert.match(v.get('κόρ᾽').note, /printed nowhere.*reads as κόρη \/ κόρος/);
  assert.equal(level('ὄρεισα'), 'warn');
  assert.equal(level('σελήνη'), 'bad'); assert.match(v.get('σελήνη').note, /Lesbian poets print σελάννα \(Sappho 154\)/);
  assert.equal(level('ξζψ'), 'bad');
  assert.equal(level('βραδύ'), 'unknown');
});
test('no dialect: anything printed in the corpus is ok; malformed evidence is ignored', () => {
  const v = C.attestWords([{ id: 'L4', evidence: [{ form: 'σελήνη', tokens: 84, dialect_tokens: null, author_tokens: null }, null, { tokens: 3 }] }], {});
  assert.equal(v.get('σελήνη').level, 'ok');
  assert.equal(v.size, 1);
  assert.equal(C.attestWords(null).size, 0);
  const foreign = C.attestWords([{ id: 'L2', evidence: [{ form: 'σελάννα', dialects: { lesbian: 9 } }] }], { dialect: 'Ionic' });
  assert.equal(foreign.get('σελάννα').level, 'warn');
});
