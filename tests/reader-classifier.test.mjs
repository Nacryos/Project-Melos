import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('  function formatFeatures('), source.indexOf('  function claimValue('))
  + source.slice(source.indexOf('  function candidateEntrySenses('), source.indexOf('  function renderSourceGrammarAlternatives('))
  + source.slice(source.indexOf('  function candidatePreferenceLabel('), source.indexOf('  function addContextAction(')), context);
const label = vm.runInContext('candidatePreferenceLabel', context);

test('model preference labels distinguish grammatical alternatives to the same lemma', () => {
  const base = { lemma: 'fixture lemma' };
  const nom = label({ ...base, analysis: ['neuter', 'nominative', 'singular'] });
  const acc = label({ ...base, analysis: ['neuter', 'accusative', 'singular'] });
  assert.notEqual(nom, acc);
  assert.match(nom, /nominative/);
  assert.match(acc, /accusative/);
});

test('partial and equivalent-form claims are not labelled as complete parses', () => {
  assert.match(label({ lemma: 'fixture' }), /No grammatical analysis supplied/);
  assert.match(label({ matched_form: 'fixture', equivalent_form: 'other fixture' }), /Equivalent form: other fixture/);
  assert.match(label({ matched_form: 'fixture', features: { mood: 'infinitive', voice: 'active' } }), /active · infinitive/);
});
