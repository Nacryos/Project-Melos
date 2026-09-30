import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Entirely synthetic entry/parse fixtures; these are not Greek corpus evidence.
const context = vm.createContext({ window: {}, URL });
vm.runInContext(readFileSync(new URL('../js/dictionary-preview.js', import.meta.url), 'utf8'), context);
const { isCandidateQuery, buildPreview } = context.window.MelosDictionaryPreview;
function fixture() {
  return { form: 'λόγου', match_status: 'indexed_match',
    candidates: [{ lemma: 'λόγος', match_kind: 'indexed_form', edit_distance: 0,
      matched_form: 'λόγου', analysis: 'fixture recorded parse', analysis_text: 'fixture readable parse',
      source: 'Fixture treebank', source_url: 'https://example.test/treebank',
      lexicon_entry_ids: ['entry:a'], gloss_entry_id: 'entry:a' }],
    lexicon_entries: [{ id: 'entry:a', lemma: 'λόγος', gloss: 'Fixture meaning; with a qualifying phrase.',
      source: 'Fixture lexicon', source_url: 'https://example.test/lexicon/a' }] };
}

test('single Greek/transliterated words accepted without mistaking descriptions for words', () => {
  for (const query of ['λόγος', 'LOGOS', 'lo/gos', 'a)/mmi', 'ἄμμ’']) assert.equal(isCandidateQuery(query), true);
  for (const query of ['', 'a garden of roses', 'Sappho 31', '31', '<script>', 'x'.repeat(81)]) assert.equal(isCandidateQuery(query), false);
});

test('projects actual linked dictionary gloss and recorded parse with separate provenance', () => {
  const result = buildPreview(fixture());
  assert.equal(result.entries.length, 1);
  assert.equal(result.entries[0].lemma, 'λόγος');
  assert.equal(result.entries[0].meanings.length, 1); // Semicolon is not a fabricated sense division.
  assert.equal(result.entries[0].meanings[0].text, 'Fixture meaning; with a qualifying phrase.');
  assert.equal(result.entries[0].meanings[0].source_url, 'https://example.test/lexicon/a');
  assert.equal(result.entries[0].analyses[0].text, 'fixture readable parse');
  assert.equal(result.entries[0].analyses[0].source_url, 'https://example.test/treebank');
  assert.equal(result.ambiguous, false);
});

test('nearby spellings and unlinked dictionary entries never become definitions of query', () => {
  const data = fixture();
  data.candidates[0].edit_distance = 1;
  assert.equal(buildPreview(data).entries.length, 0);
  data.candidates[0].edit_distance = 0;
  data.candidates[0].lexicon_entry_ids = [];
  delete data.candidates[0].gloss_entry_id;
  assert.equal(buildPreview(data).entries.length, 0);
});

test('different accents/case are not silently merged into one lemma', () => {
  const data = fixture();
  data.lexicon_entries[0].lemma = 'λογός';
  assert.equal(buildPreview(data).entries.length, 0);
});

test('quarantined, inconsistent, inferred and review-only records excluded', () => {
  for (const flag of [{ quarantined: true }, { source_consistent: false }, { quality: 'needs_review' },
    { status: 'source_inconsistent' }, { assertion_type: 'model_inference' }]) {
    const data = fixture(); Object.assign(data.candidates[0], flag);
    assert.equal(buildPreview(data).entries.length, 0);
    const second = fixture(); Object.assign(second.lexicon_entries[0], flag);
    assert.equal(buildPreview(second).entries.length, 0);
  }
});

test('homographs remain distinct cards without falsely assigning a form parse to either', () => {
  const data = fixture();
  data.lexicon_entries.push({ ...data.lexicon_entries[0], id: 'entry:b', gloss: 'Different fixture homograph meaning.' });
  data.candidates[0].lexicon_entry_ids.push('entry:b');
  const result = buildPreview(data);
  assert.equal(result.entries.length, 2);
  assert.equal(result.ambiguous, true);
  assert.equal(result.entries[0].analyses.length, 0);
  assert.equal(result.entries[1].analyses.length, 0);
  assert.match(result.entries[0].label, /unresolved/);
});

test('conflicting lemma and parse alternatives are explicitly ambiguous', () => {
  const data = fixture();
  data.candidates[0].lemma_link_status = 'ambiguous_source_lemmas';
  assert.equal(buildPreview(data).ambiguous, true);
  delete data.candidates[0].lemma_link_status;
  data.candidates.push({ ...data.candidates[0], analysis_text: 'another recorded parse' });
  assert.equal(buildPreview(data).entries[0].analyses.length, 2);
  assert.equal(buildPreview(data).ambiguous, true);
});

test('unsupported compact postags are not displayed as additional parsing alternatives', () => {
  const data = fixture();
  data.candidates.push({ ...data.candidates[0], analysis_text: null,
    analysis: 'v3spie--------', analysis_format: 'Perseus treebank 1.6 postag' });
  const result = buildPreview(data);
  assert.equal(result.entries[0].analyses.length, 1);
  assert.equal(result.entries[0].analyses[0].text, 'fixture readable parse');
  assert.equal(result.ambiguous, false);
  delete data.candidates[1].analysis_format;
  assert.equal(buildPreview(data).entries[0].analyses.length, 1);
});

test('long gloss is literal bounded prefix, never generative simplification', () => {
  const data = fixture();
  data.lexicon_entries[0].gloss = 'This fixture qualifier remains part of the excerpt. '.repeat(12);
  const result = buildPreview(data), meaning = result.entries[0].meanings[0];
  assert.equal(meaning.truncated, true);
  assert.equal(data.lexicon_entries[0].gloss.startsWith(meaning.text.slice(0, -1)), true);
  assert.ok(meaning.text.length <= 201);
  assert.equal(result.truncated, true);
});

test('missing actual gloss never falls back to generated candidate text or entire entry', () => {
  const data = fixture(); delete data.lexicon_entries[0].gloss;
  data.lexicon_entries[0].rendered_entry_text = 'Entire entry is not an extracted definition.';
  data.candidates[0].gloss = 'Unscoped candidate gloss';
  assert.equal(buildPreview(data).entries.length, 0);
});

test('unsafe source links are rejected, safe source text is not interpreted as HTML', () => {
  const data = fixture(); data.lexicon_entries[0].source_url = 'javascript:alert(1)';
  assert.equal(buildPreview(data).entries.length, 0);
  data.lexicon_entries[0].source_url = 'https://example.test/lexicon';
  data.lexicon_entries[0].gloss = '<img src=x onerror=alert(1)>';
  assert.equal(buildPreview(data).entries[0].meanings[0].text, '<img src=x onerror=alert(1)>');
});

test('Wiktionary uses separately supplied senses and exact listed-form tags', () => {
  const wiki = { ready: true, query: 'λόγου', results: [{ id: 'wiki:1', headword: 'λόγος',
    source: 'Fixture Wiki', source_url: 'https://example.test/archive', live_entry_url: 'https://example.test/live',
    matches: [{ kind: 'listed_form', form: { form: 'λόγου', tags: ['fixture-case', 'fixture-number'] } }],
    senses: [0, 1, 2, 3].map(index => ({ sense_index: index, glosses: [`Fixture sense ${index}.`] })), total_senses: 4 }] };
  const result = buildPreview({ form: 'λόγου', candidates: [], lexicon_entries: [] }, wiki);
  assert.equal(result.entries.length, 1);
  assert.equal(result.entries[0].meanings.length, 3);
  assert.equal(result.entries[0].meanings[2].sense_index, 2);
  assert.equal(result.entries[0].analyses[0].text, 'fixture-case, fixture-number');
  assert.match(result.entries[0].analyses[0].label, /not a corpus attestation/);
  assert.equal(result.entries[0].source_url, 'https://example.test/archive');
  assert.equal(result.entries[0].entry_url, 'https://example.test/live');
  assert.equal(result.truncated, true);
  assert.equal(buildPreview({ form: 'λόγου', match_status: 'spelling_suggestions_only' }, wiki).entries.length, 1);
  assert.equal(buildPreview({ form: 'different-query' }, wiki).entries.length, 0);
  wiki.ready = false;
  assert.equal(buildPreview({ form: 'λόγου' }, wiki).entries.length, 0);
});

function wikiFixture(query, headword, matches) {
  return { ready: true, query, results: [{ id: 'wiki:synthetic', headword,
    source: 'Fixture Wiki', source_url: 'https://example.test/wiki', matches,
    senses: [{ sense_index: 0, glosses: ['Synthetic source definition.'] }], total_senses: 1 }] };
}

test('Wiktionary lexical-list tags are not grammatical inflection analyses', () => {
  const query = 'ἄμμι';
  const wiki = wikiFixture(query, 'ἄμι', [
    { kind: 'listed_form', form: { form: query, tags: ['canonical', 'alternative', 'romanization'] } },
    { kind: 'listed_form', form: { form: query, tags: ['alternative', 'dative', 'plural'] } }
  ]);
  const result = buildPreview({ form: query }, wiki);
  assert.equal(result.entries.length, 1);
  assert.equal(result.entries[0].analyses.length, 1);
  assert.equal(result.entries[0].analyses[0].text, 'dative, plural');
});

test('Wiktionary suffix/headword punctuation cannot disappear into a standalone-word meaning', () => {
  for (const suffix of ['-λογος', '-λόγος']) {
    const wiki = wikiFixture('λόγος', suffix, [{ kind: 'headword', word: suffix }]);
    assert.equal(buildPreview({ form: 'λόγος' }, wiki).entries.length, 0);
    wiki.results[0].matches = [{ kind: 'listed_form', form: { form: suffix, tags: ['nominative'] } }];
    assert.equal(buildPreview({ form: 'λόγος' }, wiki).entries.length, 0);
  }
});

test('Wiktionary exact Greek listed forms retain accent and quantity folding without Latin guesses', () => {
  const wiki = wikiFixture('βλεφάροις', 'βλέφαρον', [
    { kind: 'listed_form', form: { form: 'βλεφᾰ́ροις', tags: ['dative', 'plural'] } }
  ]);
  assert.equal(buildPreview({ form: 'βλεφάροις' }, wiki).entries.length, 1);
  const latin = wikiFixture('love', 'λοβός', [{ kind: 'listed_form', form: { form: 'λοβέ', tags: ['vocative'] } }]);
  assert.equal(buildPreview({ form: 'love' }, latin).entries.length, 0);
});
