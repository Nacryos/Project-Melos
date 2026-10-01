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
  assert.match(script, /candidateDictionaryExcerpt\(candidate, data\.lexicon_entries\)/);
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
