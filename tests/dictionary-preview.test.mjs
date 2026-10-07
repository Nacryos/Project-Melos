import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Entirely synthetic entry/parse fixtures; these are not Greek corpus evidence.
const context = vm.createContext({ window: {}, URL });
vm.runInContext(readFileSync(new URL('../js/dictionary-preview.js', import.meta.url), 'utf8'), context);
const { isCandidateQuery, buildPreview, friendlySourceName, definitionExcerpt } = context.window.MelosDictionaryPreview;
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

test('structured dictionary senses replace legacy etymological glosses and keep source identities', () => {
  const data = fixture(), entry = data.lexicon_entries[0];
  entry.gloss = 'OLD_ETYMOLOGY_MUST_NOT_RENDER';
  entry.dictionary_senses = [0, 1].map(index => ({ id: `sense:${index}`, entry_id: 'native-xml-id', lexicon_entry_id: entry.id,
    text: `Synthetic literal meaning ${index}`, evidence_type: 'dictionary_sense', language: 'en',
    source: entry.source, source_url: entry.source_url, qualifiers: ['fixture qualifier'], scope_text: 'Synthetic scope' }));
  const result = buildPreview(data);
  assert.equal(result.entries[0].meaning_kind, 'structured_dictionary_gloss');
  assert.equal(result.entries[0].meanings.length, 2);
  assert.equal(result.entries[0].meanings[1].sense_id, 'sense:1');
  assert.equal(result.entries[0].meanings[0].provenance[0].lexicon_entry_id, entry.id);
  assert.equal(definitionExcerpt(entry).text, 'Synthetic literal meaning 0');
  assert.doesNotMatch(JSON.stringify(result), /OLD_ETYMOLOGY_MUST_NOT_RENDER/);
});

test('empty, invalid or mismatched structured senses never resurrect a legacy gloss', () => {
  for (const patch of [{ dictionary_senses: [] }, { dictionary_senses_status: 'unavailable' },
    { dictionary_senses: [{ id: 'wrong', entry_id: 'another-entry', text: 'Wrong source', evidence_type: 'dictionary_sense', language: 'en', source_url: 'https://example.test' }] },
    { dictionary_senses: [{ id: 'wrong-language', entry_id: 'entry:a', text: 'NON_ENGLISH', evidence_type: 'dictionary_sense', language: 'el', source_url: 'https://example.test' }] }]) {
    const data = fixture(); Object.assign(data.lexicon_entries[0], patch);
    assert.equal(buildPreview(data).entries.length, 0);
    assert.equal(definitionExcerpt(data.lexicon_entries[0]), null);
  }
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

test('verified LSJ definition clause is preferred without changing the source gloss', () => {
  const data = fixture();
  const entry = data.lexicon_entries[0];
  entry.entry_id = 'lsj:fixture:1';
  entry.source = 'PerseusDL LSJ TEI';
  entry.gloss = 'Skt. comparative preamble; man, opp. woman; person.';
  entry.definition_excerpt = 'man, opp. woman; person.';
  entry.definition_excerpt_provenance = {
    source_url: entry.source_url, entry_id: entry.entry_id, raw_sha256: 'a'.repeat(64),
    method: 'Source definition clause after an explicit balanced Sanskrit comparative preamble; no contextual sense adjudication.',
    source_locator: { sense_id: 'sense1', boundary_ordinal: 1, rendered_start: 27,
      rendered_end: 51, offset_basis: 'uncompacted Greek-span-rendered TEI entry' }
  };
  const original = structuredClone(data);
  const result = buildPreview(data);
  assert.deepEqual(data, original);
  assert.equal(definitionExcerpt(entry).text, 'man, opp. woman; person.');
  assert.equal(result.entries[0].meanings[0].text, 'man, opp. woman; person.');
  assert.equal(result.entries[0].meanings[0].definition_excerpt_provenance.entry_id, entry.entry_id);
  assert.equal(entry.gloss, 'Skt. comparative preamble; man, opp. woman; person.');
  entry.status = 'needs_review';
  assert.equal(definitionExcerpt(entry), null);
  delete entry.status;
  entry.assertion_type = 'model_inference';
  assert.equal(definitionExcerpt(entry), null);
});

test('unbound LSJ display clause falls back to the original gloss', () => {
  const data = fixture();
  const entry = data.lexicon_entries[0];
  entry.entry_id = 'lsj:fixture:1';
  entry.source = 'PerseusDL LSJ TEI';
  entry.gloss = 'Original source gloss.';
  entry.definition_excerpt = 'Unverified clause.';
  entry.definition_excerpt_provenance = { source_url: entry.source_url, entry_id: 'different-entry',
    raw_sha256: 'a'.repeat(64), method: 'Fixture source extraction.',
    source_locator: { boundary_ordinal: 1, rendered_start: 0, rendered_end: 18,
      offset_basis: 'uncompacted Greek-span-rendered TEI entry' } };
  const result = buildPreview(data);
  assert.equal(result.entries[0].meanings[0].text, 'Original source gloss.');
  assert.equal(result.entries[0].meanings[0].definition_excerpt_provenance, undefined);
  assert.equal(definitionExcerpt(entry), null);
  assert.equal(definitionExcerpt(null), null);
  entry.definition_excerpt_provenance.entry_id = entry.entry_id;
  entry.definition_excerpt_provenance.source_locator.boundary_ordinal = 0;
  assert.equal(definitionExcerpt(entry), null);
  entry.definition_excerpt_provenance.source_locator.boundary_ordinal = 1;
  entry.source_url = 'javascript:unsafe()';
  entry.definition_excerpt_provenance.source_url = entry.source_url;
  assert.equal(definitionExcerpt(entry), null);
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

test('source-shaped Πατήρ/Πάτερ records do not attach a vocative gloss to searched nominative πατήρ', () => {
  // Exact source-shaped Kaikki scopes, used only as UI fixtures, not corpus data.
  const wiki = { ready: true, query: 'πατήρ', results: [
    { id: 'wiktionary:kaikki:line:177', headword: 'πατήρ', pos: 'noun',
      source: 'Wiktionary / Kaikki', source_url: 'https://example.test/kaikki',
      matches: [
        { kind: 'headword', word: 'πατήρ' },
        { kind: 'listed_form', form_index: 0, form: { form: 'πᾰτήρ', tags: ['canonical', 'masculine'] } },
        { kind: 'listed_form', form_index: 7, form: { form: 'πᾰτήρ', tags: ['nominative', 'singular'] } },
      ], senses: [{ sense_index: 0, glosses: ['father'] }], total_senses: 1 },
    { id: 'wiktionary:kaikki:line:36869', headword: 'Πατήρ', pos: 'name',
      source: 'Wiktionary / Kaikki', source_url: 'https://example.test/kaikki',
      matches: [{ kind: 'headword', word: 'Πατήρ' },
        { kind: 'listed_form', form_index: 6, form: { form: 'Πᾰτήρ', tags: ['nominative', 'singular'] } }],
      senses: [{ sense_index: 0, glosses: ['God the Father; (one of the three Persons of the Trinity)'] }],
      total_senses: 1 },
    { id: 'wiktionary:kaikki:line:36875', headword: 'Πάτερ', pos: 'name',
      source: 'Wiktionary / Kaikki', source_url: 'https://example.test/kaikki',
      matches: [{ kind: 'listed_form', form_index: 4,
        form: { form: 'Πᾰτήρ', tags: ['nominative', 'singular'], source: 'declension' } }],
      senses: [{ sense_index: 0, glosses: ['vocative singular of Πᾰτήρ (Pătḗr)'],
        tags: ['form-of', 'singular', 'vocative'], form_of: [{ word: 'Πᾰτήρ', extra: 'Pătḗr' }] }],
      total_senses: 1 },
  ] };
  const original = structuredClone(wiki);
  const result = buildPreview({ form: 'πατήρ' }, wiki);
  assert.deepEqual(wiki, original); // The source/API payload is never rewritten.
  assert.deepEqual(Array.from(result.entries, entry => entry.id),
    ['wiktionary:kaikki:line:177']);
  assert.equal(result.compact.entries.length, 1);
  assert.ok(!JSON.stringify(result.compact).includes('vocative singular of Πᾰτήρ'));
  assert.equal(result.entries[0].analyses.length, 0);
  assert.ok(result.entries[0].normalized_analyses.some(row => row.text === 'nominative, singular'));
  assert.ok(!JSON.stringify(result.entries[0].analyses).includes('masculine'));
  assert.equal(result.normalized_alternatives[0].meanings[0].text, 'God the Father; (one of the three Persons of the Trinity)');
});

test('direct Πάτερ and ὄμμασι headwords retain source form-of glosses and sense grammar', () => {
  for (const [query, target, tags, gloss] of [
    ['Πάτερ', 'Πᾰτήρ', ['form-of', 'singular', 'vocative'], 'vocative singular of Πᾰτήρ'],
    ['ὄμμασι', 'ὄμμᾰ', ['dative', 'form-of', 'plural'], 'dative plural of ὄμμᾰ'],
  ]) {
    const wiki = wikiFixture(query, query, [
      { kind: 'headword', word: query },
      { kind: 'listed_form', form: { form: query, tags: ['canonical', 'masculine'] } },
    ]);
    wiki.results[0].senses = [{ sense_index: 0, glosses: [gloss], tags,
      form_of: [{ word: target }] }];
    const result = buildPreview({ form: query }, wiki);
    assert.equal(result.entries.length, 1);
    assert.equal(result.entries[0].meanings[0].text, gloss);
    assert.equal(result.entries[0].analyses[0].text, tags.filter(tag => tag !== 'form-of').join(', '));
    assert.match(result.entries[0].analyses[0].label, /form-of sense tags/);
    assert.equal(result.compact.entries.length, 1);
  }
});

test('mixed lexical and form-of senses retain only applicable glosses for a different listed form', () => {
  const wiki = wikiFixture('πατήρ', 'Πάτερ', [
    { kind: 'listed_form', form: { form: 'πατήρ', tags: ['nominative', 'singular'] } },
  ]);
  wiki.results[0].senses = [
    { sense_index: 0, glosses: ['Source lexical sense.'] },
    { sense_index: 1, glosses: ['vocative singular of Πᾰτήρ'],
      tags: ['form-of', 'singular', 'vocative'], form_of: [{ word: 'Πᾰτήρ' }] },
  ];
  const result = buildPreview({ form: 'πατήρ' }, wiki);
  assert.equal(result.entries.length, 1);
  assert.deepEqual(Array.from(result.entries[0].meanings, row => row.text), ['Source lexical sense.']);
  assert.deepEqual(Array.from(result.entries[0].analyses, row => row.text), ['nominative, singular']);
  assert.ok(!JSON.stringify(result.compact).includes('vocative'));
});

test('review-only form-of sense tags cannot leak into a direct-headword analysis', () => {
  const wiki = wikiFixture('Πάτερ', 'Πάτερ', [{ kind: 'headword', word: 'Πάτερ' }]);
  wiki.results[0].senses = [
    { sense_index: 0, glosses: ['Source-approved form-of gloss.'],
      tags: ['form-of', 'singular', 'vocative'], form_of: [{ word: 'Πᾰτήρ' }] },
    { sense_index: 1, status: 'needs_review', glosses: ['Unaccepted reading.'],
      tags: ['form-of', 'plural', 'nominative'], form_of: [{ word: 'Πᾰτήρ' }] },
  ];
  const result = buildPreview({ form: 'Πάτερ' }, wiki);
  assert.deepEqual(Array.from(result.entries[0].analyses, row => row.text), ['singular, vocative']);
  assert.deepEqual(Array.from(result.entries[0].meanings, row => row.text), ['Source-approved form-of gloss.']);
});

test('Wiktionary suffix/headword punctuation cannot disappear into a standalone-word meaning', () => {
  for (const suffix of ['-λογος', '-λόγος']) {
    const wiki = wikiFixture('λόγος', suffix, [{ kind: 'headword', word: suffix }]);
    assert.equal(buildPreview({ form: 'λόγος' }, wiki).entries.length, 0);
    wiki.results[0].matches = [{ kind: 'listed_form', form: { form: suffix, tags: ['nominative'] } }];
    assert.equal(buildPreview({ form: 'λόγος' }, wiki).entries.length, 0);
  }
});

test('Wiktionary accent and quantity folding yields alternatives, not exact parses or Latin guesses', () => {
  const wiki = wikiFixture('βλεφάροις', 'βλέφαρον', [
    { kind: 'listed_form', form: { form: 'βλεφᾰ́ροις', tags: ['dative', 'plural'] } }
  ]);
  const preview = buildPreview({ form: 'βλεφάροις' }, wiki);
  assert.equal(preview.entries.length, 0);
  assert.equal(preview.normalized_alternatives.length, 1);
  assert.equal(preview.normalized_alternatives[0].analyses.length, 0);
  assert.equal(preview.normalized_alternatives[0].normalized_analyses[0].text, 'dative, plural');
  const latin = wikiFixture('love', 'λοβός', [{ kind: 'listed_form', form: { form: 'λοβέ', tags: ['vocative'] } }]);
  assert.equal(buildPreview({ form: 'love' }, latin).entries.length, 0);
});
test('normalized-only headword cannot lend form-of grammar to an exact table match', () => {
  const wiki = wikiFixture('α', 'ά', [{ kind: 'headword', word: 'ά' },
    { kind: 'listed_form', form: { form: 'α', tags: ['second-person'] } }]);
  wiki.results[0].senses = [{ tags: ['form-of', 'first-person'], form_of: [{ word: 'β' }], glosses: ['headword-specific grammar'] }];
  assert.equal(buildPreview({ form: 'α' }, wiki).entries.length, 0);
});
test('inherited multi-gloss entries without grammatical scope are not rewritten as table-form meanings', () => {
  const wiki = wikiFixture('α', 'β', [{ kind: 'listed_form', form: { form: 'α', tags: ['second-person'] } }]);
  wiki.results[0].senses = [{ glosses: ['parent headword grammar', 'nested lexical wording'] }];
  assert.equal(buildPreview({ form: 'α' }, wiki).entries.length, 0);
});
test('captured live Wiki scope preserves exact selected form but excludes unrelated nested headword definitions', () => {
  const wiki = JSON.parse(readFileSync(new URL('./fixtures/wiktionary-elthes-live.json', import.meta.url), 'utf8'));
  const preview = buildPreview({ form: wiki.query }, wiki);
  assert.ok(preview.entries.some(entry => entry.lemma === wiki.query));
  const inherited = wiki.results.filter(item => item.headword !== wiki.query).flatMap(item => item.senses)
    .filter(sense => sense.glosses.length > 1).map(sense => sense.glosses[0]);
  for (const text of inherited) assert.ok(!JSON.stringify(preview.compact).includes(text));
});

test('compact meanings prefer structured literal glosses and retain full source entries separately', () => {
  const data = fixture();
  data.lexicon_entries.push({ ...data.lexicon_entries[0], id: 'entry:b', source: 'Other fixture dictionary', gloss: 'Another long dictionary excerpt.' });
  data.candidates[0].lexicon_entry_ids.push('entry:b');
  const wiki = wikiFixture(data.form, 'λόγος', [{ kind: 'listed_form', form: { form: data.form, tags: ['genitive'] } }]);
  wiki.results[0].senses = [
    { sense_index: 0, glosses: ['Short first fixture meaning.'] },
    { sense_index: 1, glosses: ['Short first fixture meaning.'] },
    { sense_index: 2, glosses: ['Short second fixture meaning.'] }
  ];
  wiki.results[0].total_senses = 3;
  const result = buildPreview(data, wiki);
  assert.equal(result.entries.length, 3);
  assert.equal(result.compact.entries.length, 1);
  assert.equal(result.compact.entries[0].id, 'wiki:synthetic');
  assert.equal(result.compact.entries[0].meanings.length, 2);
  const first = result.compact.entries[0].meanings[0];
  assert.deepEqual(Array.from(first.sense_indices), [0, 1]);
  assert.equal(first.provenance.length, 2);
  assert.equal(first.provenance[1].entry_id, 'wiki:synthetic');
  assert.equal(first.provenance[1].sense_index, 1);
  assert.equal(result.compact.omitted_entry_count, 2);
  assert.equal(result.compact.omitted_meaning_count, 2);
  assert.equal(result.compact.entries[0].analyses[0].text, 'genitive');
  assert.ok(!result.compact.entries[0].analyses.some(row => row.text === 'fixture readable parse'));
});

test('dictionary-only compact view chooses one excerpt without losing other source-entry actions', () => {
  const data = fixture();
  data.lexicon_entries.push({ ...data.lexicon_entries[0], id: 'entry:b', source: 'Other fixture dictionary' });
  data.candidates[0].lexicon_entry_ids.push('entry:b');
  const result = buildPreview(data);
  assert.equal(result.entries.length, 2);
  assert.equal(result.compact.entries.length, 1);
  assert.equal(result.compact.entries[0].meanings.length, 1);
  assert.equal(result.compact.omitted_entries[0].id, 'entry:b');
});

test('compact selection keeps same-spelling homographs separate even when glosses are identical', () => {
  const wiki = wikiFixture('λόγος', 'λόγος', [{ kind: 'headword', word: 'λόγος' }]);
  wiki.results.push({ ...wiki.results[0], id: 'wiki:other-homograph' });
  const result = buildPreview({ form: 'λόγος' }, wiki);
  assert.equal(result.entries.length, 2);
  assert.equal(result.compact.entries.length, 2);
  assert.equal(result.compact.entries[0].meanings[0].text, result.compact.entries[1].meanings[0].text);
  assert.notEqual(result.compact.entries[0].meanings[0].provenance[0].entry_id,
    result.compact.entries[1].meanings[0].provenance[0].entry_id);
  assert.equal(result.compact.ambiguous, true);
});

test('three-meaning budget reports every hidden alternative and does not impose the old six-entry cap', () => {
  const data = fixture();
  data.lexicon_entries = Array.from({ length: 8 }, (_, index) => ({
    ...data.lexicon_entries[0], id: `entry:${index}`, lemma: `lemma-${index}`, gloss: `Literal fixture meaning ${index}.`
  }));
  data.candidates = data.lexicon_entries.map(entry => ({
    ...data.candidates[0], lemma: entry.lemma, lexicon_entry_ids: [entry.id], gloss_entry_id: entry.id
  }));
  const result = buildPreview(data);
  assert.equal(result.entries.length, 8);
  assert.equal(result.compact.entries.length, 3);
  assert.equal(result.compact.entries.reduce((sum, entry) => sum + entry.meanings.length, 0), 3);
  assert.equal(result.compact.omitted_entry_count, 5);
  assert.equal(result.compact.omitted_meaning_count, 5);
  assert.equal(result.compact.omitted_entries[4].lemma, 'lemma-7');
  assert.equal(result.compact.ambiguous, true);
});

test('glosses with identical shortened prefixes but distinct full qualifiers are not deduplicated', () => {
  const wiki = wikiFixture('λόγος', 'λόγος', [{ kind: 'headword', word: 'λόγος' }]);
  const prefix = 'Long common literal fixture qualifier. '.repeat(10);
  wiki.results[0].senses = [
    { sense_index: 0, glosses: [prefix + 'first ending'] },
    { sense_index: 1, glosses: [prefix + 'different ending'] }
  ];
  const result = buildPreview({ form: 'λόγος' }, wiki);
  assert.equal(result.entries[0].meanings.length, 2);
  assert.equal(result.entries[0].meanings[0].provenance.length, 1);
  assert.equal(result.entries[0].meanings[1].provenance.length, 1);
});

test('friendly source names use established exact labels and preserve unknown names', () => {
  assert.equal(friendlySourceName('PerseusDL LSJ TEI'), 'LSJ');
  assert.equal(friendlySourceName('Perseus Autenrieth TEI via Homerica'), 'Autenrieth');
  assert.equal(friendlySourceName('Kaikki Ancient Greek postprocessed enwiktionary extraction'), 'Wiktionary');
  assert.equal(friendlySourceName('PerseusDL Greek Dependency Treebank v1.6'), 'Perseus treebank');
  assert.equal(friendlySourceName('Unverified notes mentioning LSJ'), 'Unverified notes mentioning LSJ');
});
