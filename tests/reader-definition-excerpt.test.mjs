import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Display-only fixtures, not corpus claims or source-data additions.
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
const received = [];
const context = vm.createContext({ window: { MelosDictionaryPreview: {
  definitionExcerpt(entry) { received.push(entry.id); return entry.valid ? { text: 'Literal definition clause', provenance: { entry_id: 'fixture' } } : null; }
} } });
vm.runInContext(script.slice(script.indexOf('  function candidateDictionaryExcerpt('), script.indexOf('  async function inspectWord(')), context);
const project = vm.runInContext('candidateDictionaryExcerpt', context);

test('recorded analysis uses the validated definition only from its exact linked entry', () => {
  const candidate = { gloss_entry_id: 'source:fixture', gloss: 'Unmodified stored gloss' };
  const entries = [{ id: 'source:unrelated', valid: true }, { id: 'source:fixture', valid: true }];
  assert.equal(project(candidate, entries).text, 'Literal definition clause');
  assert.equal(received.at(-1), 'source:fixture');
  assert.equal(candidate.gloss, 'Unmodified stored gloss');
  assert.match(script, /candidateDictionaryExcerpt\(candidate, data\.lexicon_entries, form\)/);
  assert.match(script, /node\('p', 'candidate-gloss', definition\.text\)/);
});

test('missing, ambiguous or rejected links retain the original gloss without guessing', () => {
  const candidate = { gloss_entry_id: 'source:fixture', gloss: 'Unmodified stored gloss' };
  for (const entries of [null, [], [{ id: 'other', valid: true }], [{ id: 'source:fixture', valid: false }],
    [{ id: 'source:fixture', valid: true }, { id: 'source:fixture', valid: true }]]) {
    assert.equal(project(candidate, entries).text, candidate.gloss);
  }
  assert.equal(project({ gloss: 'Stored' }, [{ valid: true }]).text, 'Stored');
  const previous = context.window.MelosDictionaryPreview;
  context.window.MelosDictionaryPreview = undefined;
  assert.equal(project(candidate, [{ id: 'source:fixture', valid: true }]).text, candidate.gloss);
  context.window.MelosDictionaryPreview = previous;
});

test('structured fields prevent legacy etymology fallback in candidate and linked-entry surfaces', () => {
  const candidate = { id: 'candidate:1', gloss_entry_id: 'source:fixture', gloss: 'OLD_ETYMOLOGY' };
  assert.equal(project(candidate, [{ id: 'source:fixture', dictionary_senses: [] }]).text, '');
  assert.equal(project({ ...candidate, dictionary_senses_status: 'unavailable' }, []).text, '');
  assert.equal(project({ ...candidate, dictionary_senses: [] }, [{ id: 'source:fixture', valid: true }]).text, '');
  const definition = project(candidate, [{ id: 'source:fixture', valid: true, dictionary_senses: [] }]);
  assert.equal(definition.text, 'Literal definition clause');
  assert.equal(definition.structured, true);
  assert.match(script, /if \(!definition\.structured\) for \(const gloss of candidate\.glosses/);
  assert.match(script, /candidateDictionaryExcerpt\(chosen, \[\], form\)\.text/);
});

test('actual aorist source card passes exact clicked form into the shared candidate-bound excerpt', () => {
  const liveContext=vm.createContext({window:{},URL});
  vm.runInContext(readFileSync(new URL('../js/dictionary-preview.js',import.meta.url),'utf8'),liveContext);
  vm.runInContext(script.slice(script.indexOf('  function candidateDictionaryExcerpt('), script.indexOf('  async function inspectWord(')),liveContext);
  const render=vm.runInContext('candidateDictionaryExcerpt',liveContext);
  const data=JSON.parse(readFileSync(new URL('./fixtures/word-elthes-tense-preview.json',import.meta.url),'utf8'));
  const before=JSON.stringify(data),result=render(data.candidates[0],data.lexicon_entries,data.form);
  assert.equal(result.text,'come or go');assert.equal(result.structured,true);
  assert.equal(render(data.candidates[0],data.lexicon_entries,'ἤλθες').text,'start, set out');
  assert.equal(JSON.stringify(data),before);
});
