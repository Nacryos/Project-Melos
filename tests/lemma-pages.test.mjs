import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
function load(...files) {
  const context = vm.createContext({ window: {}, URL, URLSearchParams, console });
  for (const file of files) vm.runInContext(read(file), context);
  return context.window;
}

test('shared helpers word dates, periods and rates plainly', () => {
  const { MelosLemma: L } = load('js/lemma-common.js');
  assert.equal(L.authorDate({ start: -630, end: -612, kind: 'birth', approximate: true }), 'born c. 630–612 BCE');
  assert.equal(L.authorDate({ start: 100, end: 100, kind: 'floruit' }), 'active 100 CE');
  assert.equal(L.authorDate(null), 'undated');
  assert.deepEqual({ ...L.periodParts('Archaic (to 480 BCE)') }, { name: 'Archaic', span: 'to 480 BCE' });
  assert.equal(L.periodParts('undated').undated, true);
  assert.equal(L.rate(8.78), '8.8'); assert.equal(L.rate(12.69), '13'); assert.equal(L.rate(0.38), '0.38'); assert.equal(L.rate(null), '–');
  assert.equal(L.DATE_NOTE, 'Dates are author lifetimes, not composition dates.');
  assert.equal(L.readerHref('ogc:homerus-epic.ilias.jsonl:10918'), '/?id=ogc%3Ahomerus-epic.ilias.jsonl%3A10918');
  assert.equal(L.lemmaHref('σελήνη'), `/lemma.html?lemma=${encodeURIComponent('σελήνη')}`);
  assert.equal(L.citation({ display_work: 'Iliad', citation: '17.367' }), 'Iliad 17.367');
  assert.equal(L.citation({ display_work: 'Fragment 34', citation: 'Fragment 34' }), 'Fragment 34');
  assert.equal(L.SERIES.length, 8, 'at most eight charted series, never cycled');
});

test('lexicon page state round-trips the headword, order, author filter and page', () => {
  const { MelosLemmaPage: P } = load('js/lemma-common.js', 'js/lemma-page.js');
  const state = P.readState('https://greeklyric.com/lemma.html?lemma=σελήνη&order=author&author=Nonnus&page=3&keep=1');
  assert.equal(state.lemma, 'σελήνη'); assert.equal(state.order, 'author'); assert.equal(state.author, 'Nonnus'); assert.equal(state.page, 3);
  const url = P.writeState('https://greeklyric.com/lemma.html?keep=1', { ...state, page: 1, order: 'chronological' });
  assert.equal(url.searchParams.get('keep'), '1'); assert.equal(url.searchParams.has('page'), false); assert.equal(url.searchParams.has('order'), false);
  assert.equal(P.readState(url.href).lemma, 'σελήνη');
  assert.equal(P.readState('https://x.test/lemma.html?page=-4&order=evil').page, 1);
  assert.equal(P.readState('https://x.test/lemma.html?page=-4&order=evil').order, 'chronological');
  assert.equal(P.readState(`https://x.test/lemma.html?q=${'α'.repeat(300)}`).q.length, 100);
});

test('collocation strength and query readings are put in words', () => {
  const { MelosLemmaPage: P } = load('js/lemma-common.js', 'js/lemma-page.js');
  assert.equal(P.timesChance({ count: 24, expected: 0.063 }), '381×');
  assert.equal(P.timesChance({ count: 8, expected: 0.8 }), '10×');
  assert.equal(P.timesChance({ count: 3, expected: 1.2 }), '2.5×');
  assert.equal(P.timesChance({ count: 3, expected: 0 }), '');
  assert.equal(P.viaText({ via: 'printed_form_reading' }), 'a form of');
  assert.equal(P.viaText({ via: 'english_dictionary_gloss' }), 'an English meaning of');
});

test('concept series keep undated authors apart and leave periods without texts empty', () => {
  const { MelosConceptPage: C } = load('js/lemma-common.js', 'js/concept-page.js');
  const periods = [{ label: 'Archaic (to 480 BCE)', tokens: 717809 }, { label: 'Byzantine (from 600 CE)', tokens: 0 }];
  const item = { undated_count: 148, by_period: [
    { period: 'Archaic (to 480 BCE)', count: 49, tokens_in_period: 717809, per_10k: 0.68 },
    { period: 'Byzantine (from 600 CE)', count: 0, tokens_in_period: 0, per_10k: null }] };
  const series = C.seriesFor(item, periods, 360219);
  assert.equal(series.points[0].value, 0.68); assert.ok(Number.isNaN(series.points[1].value));
  assert.equal(series.undated.count, 148); assert.equal(Math.round(series.undated.value * 100) / 100, 4.11);
  assert.equal(C.seriesFor(item, periods, 0).undated, null);
  assert.match(C.sourceText({ via: 'english_dictionary_gloss', gloss_source: 'Middle Liddell', matched_terms: ['moon'] }, 'moon'), /^Dictionary meaning: its definition in Middle Liddell uses “moon”\.$/);
  assert.match(C.sourceText({ via: 'english_dictionary_gloss', matched_terms: ['lov'] }, 'love'), /uses “love”\./);
  assert.match(C.sourceText({ via: 'semantic_neighbourhood_and_shared_gloss_word', shared_gloss_terms: ['moon'], in_nearest_passages: 17 }, 'moon'), /^Meaning index: .*closest in meaning to “moon” \(17 times\).*shares “moon”/);
});

test('pages use safe DOM building, plain words and a pinned cache-bust tag', () => {
  for (const file of ['js/lemma-common.js', 'js/lemma-page.js', 'js/concept-page.js']) {
    const source = read(file);
    assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write|eval\(/, file);
  }
  for (const page of ['lemma.html', 'concept.html']) {
    const html = read(page);
    assert.match(html, /id="site-menu-button"[^>]*aria-controls="site-menu"/, page);
    assert.match(html, /js\/site-menu\.js\?v=site-menu-\d{8}/, page);
    assert.match(html, /lemma-common\.js\?v=(?:lemma|release-[a-z])-\d{8}/, page);
    assert.doesNotMatch(html, /<script[^>]+src="https?:/, `${page} loads no third-party script`);
  }
  assert.match(read('js/concept-page.js'), /Dates are author lifetimes|DATE_NOTE/);
});

test('reader offers Headword search with Near, folds editions and links the panel headword', () => {
  const html = read('reader.html');
  assert.match(html, /name="search-mode" value="lemma"><span>Headword<\/span>/);
  assert.match(html, /id="lemma-near"/); assert.match(html, /id="lemma-window"[^>]*min="1" max="20"/);
  assert.match(read('js/site-menu.js'), /\['Lexicon', '\/lexicon'[\s\S]*\['Concepts', '\/concepts'/);
  const reader = read('js/reader.js');
  assert.match(reader, /api\('\/api\/lemma\/concordance'/); assert.match(reader, /api\('\/api\/lemma\/proximity'/);
  assert.match(reader, /ordered: snapshot\.near \? 'false' : 'true'/);
  assert.match(reader, /function renderOtherEditions\(record\)/);
  // Folding needs another collection: a formula repeated in one text stays separate.
  assert.match(reader, /if \(first && first\.collections\.has\(collection\)\) \{ ui\.resultsList\.append\(keywordLine/);
  assert.match(read('js/lemma-page.js'), /!first\.dataset\.collections\.split\(' '\)\.includes\(collection\)/);
  // The batch headwords are requested together with the passage, not after it.
  const open = reader.slice(reader.indexOf('async function openPassage('));
  assert.ok(open.indexOf('requestBatchHeadlines(id)') > 0 && open.indexOf('requestBatchHeadlines(id)') < open.indexOf("api('/api/passage'"));
  assert.match(read('js/word-panel.js'), /word-headline-link'; link\.href = `lemma\.html\?lemma=\$\{encodeURIComponent\(value\.lemma\)\}`/);
});

test('reader search URL keeps Headword mode and its Near distance', () => {
  const reader = read('js/reader.js');
  assert.match(reader, /near: snapshot\.mode === 'lemma' && snapshot\.near \? '1' : null/);
  assert.match(reader, /window: \(raw => \/\^\(\?:\[1-9\]\|1\[0-9\]\|20\)\$\/\.test\(raw\) \? Number\(raw\) : 5\)\(value\('window'\)\)/);
});
